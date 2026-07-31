import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

BOX_RE = re.compile(
    r"(?:🎁\s*)?(?:BOX|BAG)\s*:\s*(?P<left>\d+)\s*/\s*(?P<right>\d+)(?P<tail>.*)",
    re.IGNORECASE | re.DOTALL,
)
RATE_RE = re.compile(r"📈\s*Rate\s*:\s*(?P<rate>\d+(?:\.\d+)?)", re.IGNORECASE)
LEVEL_RE = re.compile(r"🎯\s*Level\s*:\s*(?P<level>\d+)", re.IGNORECASE)
VIEWS_RE = re.compile(r"👀\s*(?P<views>\d+)")
NOTE_RE = re.compile(r"📝\s*(?P<note>.+)$", re.DOTALL)
FLAG_RE = re.compile(r"[\U0001F1E6-\U0001F1FF]{2}")
COMMENT_LINE_RE = re.compile(r"^.*💬.*$", re.MULTILINE)
# Watermark "mặt trời" thường gắn cuối / trong dòng bình luận 💬
SUN_MARKER = "\u0489"  # COMBINING CYRILLIC MILLIONS SIGN (҉)


@dataclass(frozen=True)
class BoxSignal:
    box: str
    box_left: int
    box_right: int
    rate: Optional[float]
    level: Optional[int]
    views: Optional[int]
    flags: Tuple[str, ...]
    country_codes: Tuple[str, ...]
    badges: Tuple[str, ...]
    note: str

    def to_payload(self) -> dict:
        return {
            "box": self.box,
            "box_left": self.box_left,
            "box_right": self.box_right,
            "rate": self.rate,
            "level": self.level,
            "views": self.views,
            "flags": list(self.flags),
            "country_codes": list(self.country_codes),
            "badges": list(self.badges),
            "note": self.note,
        }


@dataclass(frozen=True)
class MessageFilterRule:
    name: str
    enabled: bool
    priority: Optional[int]
    boxes: Tuple[str, ...]
    min_box1: Optional[int]
    max_box1: Optional[int]
    min_box2: Optional[int]
    max_box2: Optional[int]
    countries: Tuple[str, ...]
    badges: Tuple[str, ...]
    min_rate: Optional[float]
    max_rate: Optional[float]
    min_level: Optional[int]
    max_level: Optional[int]
    min_views: Optional[int]
    max_views: Optional[int]
    note_contains: Tuple[str, ...]
    text_contains: Tuple[str, ...]
    text_regex: Optional[str]
    telegram_groups: Tuple[str, ...]
    order: int

    def priority_or(self, default_priority: int) -> int:
        return self.priority if self.priority is not None else default_priority

    def to_payload(self, default_priority: int) -> Dict[str, Any]:
        return {
            "name": self.name,
            "priority": self.priority_or(default_priority),
        }


@dataclass(frozen=True)
class RejectFilterRule:
    name: str
    enabled: bool
    text_contains: Tuple[str, ...]
    comment_contains: Tuple[str, ...]
    text_regex: Optional[str]
    order: int


@dataclass(frozen=True)
class FilterResult:
    matched: bool
    reason: str
    signal: Optional[BoxSignal]
    rule: Optional[MessageFilterRule]
    priority: Optional[int]


class MessageFilterEngine:
    def __init__(
        self,
        enabled: bool,
        config_path: str,
        reload_seconds: float,
        default_priority: int,
    ):
        self.enabled = enabled
        self.config_path = Path(config_path)
        self.reload_seconds = reload_seconds
        self.default_priority = default_priority
        self._last_loaded_at = 0.0
        self._last_mtime: Optional[float] = None
        self._rules: Tuple[MessageFilterRule, ...] = ()
        self._reject_rules: Tuple[RejectFilterRule, ...] = ()
        self._exclude_groups: Tuple[str, ...] = ()

    def evaluate(
        self,
        text: str,
        signal: Optional[BoxSignal] = None,
        *,
        chat_id: Optional[str] = None,
        chat_label: Optional[str] = None,
    ) -> FilterResult:
        signal = signal or parse_box_signal(text)
        if not self.enabled:
            return FilterResult(True, "disabled", signal, None, self.default_priority)

        self._reload_if_needed()

        if self._exclude_groups and _chat_matches_groups(
            chat_id,
            chat_label,
            self._exclude_groups,
        ):
            return FilterResult(False, "excluded_telegram_group", signal, None, None)

        for reject in self._reject_rules:
            if not reject.enabled:
                continue
            rejected, reason = _evaluate_reject_rule(text, reject)
            if rejected:
                return FilterResult(False, reason, signal, None, None)

        enabled_rules = [rule for rule in self._rules if rule.enabled]
        if not enabled_rules:
            if any(reject.enabled for reject in self._reject_rules):
                return FilterResult(
                    True,
                    "reject_only",
                    signal,
                    None,
                    self.default_priority,
                )
            return FilterResult(True, "no_filters", signal, None, self.default_priority)

        matched_rules = []
        last_reason = "not_matched"
        for rule in enabled_rules:
            matched, reason = _evaluate_rule(
                text,
                signal,
                rule,
                chat_id=chat_id,
                chat_label=chat_label,
            )
            if matched:
                matched_rules.append(rule)
            else:
                last_reason = reason

        if not matched_rules:
            return FilterResult(False, last_reason, signal, None, None)

        best_rule = sorted(
            matched_rules,
            key=lambda rule: (-rule.priority_or(self.default_priority), rule.order),
        )[0]
        return FilterResult(
            True,
            "matched",
            signal,
            best_rule,
            best_rule.priority_or(self.default_priority),
        )

    def _reload_if_needed(self) -> None:
        now = time.time()
        if now - self._last_loaded_at < self.reload_seconds:
            return

        self._last_loaded_at = now
        try:
            mtime = self.config_path.stat().st_mtime
        except FileNotFoundError:
            if self._rules or self._reject_rules:
                logger.warning("Message filter config missing path=%s", self.config_path)
            self._rules = ()
            self._reject_rules = ()
            self._exclude_groups = ()
            self._last_mtime = None
            return

        if self._last_mtime == mtime:
            return

        self._last_mtime = mtime
        self._rules, self._reject_rules, self._exclude_groups = _load_rules(self.config_path)
        enabled_count = sum(1 for rule in self._rules if rule.enabled)
        reject_count = sum(1 for rule in self._reject_rules if rule.enabled)
        logger.info(
            "Loaded message filters path=%s allow=%s reject=%s exclude_groups=%s",
            self.config_path,
            enabled_count,
            reject_count,
            len(self._exclude_groups),
        )


def parse_box_signal(text: str) -> Optional[BoxSignal]:
    box_match = BOX_RE.search(text)
    if not box_match:
        return None

    left = int(box_match.group("left"))
    right = int(box_match.group("right"))
    tail = box_match.group("tail") or ""
    meta = tail.split("📈", 1)[0]

    rate_match = RATE_RE.search(text)
    level_match = LEVEL_RE.search(text)
    views_match = VIEWS_RE.search(text)
    note_match = NOTE_RE.search(text)
    flags = tuple(FLAG_RE.findall(tail))
    country_codes = tuple(
        code for code in (_flag_to_country_code(flag) for flag in flags) if code
    )

    return BoxSignal(
        box=f"{left}/{right}",
        box_left=left,
        box_right=right,
        rate=float(rate_match.group("rate")) if rate_match else None,
        level=int(level_match.group("level")) if level_match else None,
        views=int(views_match.group("views")) if views_match else None,
        flags=flags,
        country_codes=country_codes,
        badges=_extract_badges(meta),
        note=(note_match.group("note").strip() if note_match else ""),
    )


def _load_rules(
    path: Path,
) -> Tuple[Tuple[MessageFilterRule, ...], Tuple[RejectFilterRule, ...], Tuple[str, ...]]:
    with path.open(encoding="utf-8") as file:
        raw_config = json.load(file)

    if isinstance(raw_config, dict):
        raw_rules = raw_config.get("filters", [])
        raw_reject = raw_config.get("reject", [])
        raw_exclude = (
            raw_config.get("exclude_telegram_groups")
            or raw_config.get("exclude_groups")
            or []
        )
    else:
        raw_rules = raw_config
        raw_reject = []
        raw_exclude = []

    if not isinstance(raw_rules, list):
        raise RuntimeError("message filter config must be a list or object with filters=[]")
    if not isinstance(raw_reject, list):
        raise RuntimeError("message filter reject must be a list")

    allow = tuple(_parse_rule(raw_rule, index) for index, raw_rule in enumerate(raw_rules))
    reject = tuple(
        _parse_reject_rule(raw_rule, index) for index, raw_rule in enumerate(raw_reject)
    )
    exclude = _as_tuple(raw_exclude)
    return allow, reject, exclude


def _parse_rule(raw_rule: Dict[str, Any], index: int) -> MessageFilterRule:
    if not isinstance(raw_rule, dict):
        raise RuntimeError(f"message filter #{index + 1} must be an object")

    return MessageFilterRule(
        name=str(raw_rule.get("name") or f"filter_{index + 1}"),
        enabled=bool(raw_rule.get("enabled", True)),
        priority=_optional_int(raw_rule.get("priority")),
        boxes=_as_tuple(raw_rule.get("boxes") or raw_rule.get("box")),
        min_box1=_optional_int(_first_present(raw_rule, "min_box1", "min_box_left")),
        max_box1=_optional_int(_first_present(raw_rule, "max_box1", "max_box_left")),
        min_box2=_optional_int(_first_present(raw_rule, "min_box2", "min_box_right")),
        max_box2=_optional_int(_first_present(raw_rule, "max_box2", "max_box_right")),
        countries=_as_tuple(raw_rule.get("countries") or raw_rule.get("country")),
        badges=_as_tuple(raw_rule.get("badges") or raw_rule.get("badge")),
        min_rate=_optional_float(raw_rule.get("min_rate")),
        max_rate=_optional_float(raw_rule.get("max_rate")),
        min_level=_optional_int(raw_rule.get("min_level")),
        max_level=_optional_int(raw_rule.get("max_level")),
        min_views=_optional_int(raw_rule.get("min_views")),
        max_views=_optional_int(raw_rule.get("max_views")),
        note_contains=_as_tuple(raw_rule.get("note_contains")),
        text_contains=_as_tuple(raw_rule.get("text_contains")),
        text_regex=(
            str(raw_rule.get("text_regex")).strip()
            if raw_rule.get("text_regex") not in (None, "")
            else None
        ),
        telegram_groups=_as_tuple(
            raw_rule.get("telegram_groups")
            or raw_rule.get("watch_groups")
            or raw_rule.get("groups")
        ),
        order=index,
    )


def _parse_reject_rule(raw_rule: Dict[str, Any], index: int) -> RejectFilterRule:
    if not isinstance(raw_rule, dict):
        raise RuntimeError(f"reject filter #{index + 1} must be an object")

    return RejectFilterRule(
        name=str(raw_rule.get("name") or f"reject_{index + 1}"),
        enabled=bool(raw_rule.get("enabled", True)),
        text_contains=_as_tuple(raw_rule.get("text_contains")),
        comment_contains=_as_tuple(
            raw_rule.get("comment_contains") or raw_rule.get("chat_contains")
        ),
        text_regex=(
            str(raw_rule.get("text_regex")).strip()
            if raw_rule.get("text_regex") not in (None, "")
            else None
        ),
        order=index,
    )


def _evaluate_reject_rule(text: str, rule: RejectFilterRule) -> Tuple[bool, str]:
    """Return (rejected, reason). rejected=True means do NOT forward."""
    if rule.comment_contains:
        comment = _comment_text(text)
        hits = [value for value in rule.comment_contains if value and value in comment]
        if hits:
            return True, f"rejected:{rule.name}:comment"

    if rule.text_contains:
        hits = [value for value in rule.text_contains if value and value in text]
        if hits:
            return True, f"rejected:{rule.name}:text"

    if rule.text_regex and re.search(rule.text_regex, text, re.IGNORECASE):
        return True, f"rejected:{rule.name}:regex"

    return False, "reject_not_matched"


def _comment_text(text: str) -> str:
    lines = [match.group(0) for match in COMMENT_LINE_RE.finditer(text or "")]
    return "\n".join(lines)


def _evaluate_rule(
    text: str,
    signal: Optional[BoxSignal],
    rule: MessageFilterRule,
    *,
    chat_id: Optional[str] = None,
    chat_label: Optional[str] = None,
) -> Tuple[bool, str]:
    if rule.telegram_groups and not _chat_matches_groups(
        chat_id,
        chat_label,
        rule.telegram_groups,
    ):
        return False, "telegram_group"

    if not _rule_has_constraints(rule):
        return True, "matched"

    lowered_text = text.lower()

    if rule.text_contains:
        if not any(
            value and value.lower() in lowered_text for value in rule.text_contains
        ):
            return False, "text"

    missing_notes = [
        value for value in rule.note_contains if value and value.lower() not in lowered_text
    ]
    if missing_notes:
        return False, "note"

    if rule.text_regex and not re.search(rule.text_regex, text, re.IGNORECASE):
        return False, "regex"

    if not _rule_has_signal_constraints(rule):
        return True, "matched"

    if signal is None:
        return False, "missing_box"

    boxes = {_normalize_box(value) for value in rule.boxes}
    boxes.discard("")
    if boxes and signal.box not in boxes:
        return False, "box"

    if rule.min_box1 is not None and signal.box_left < rule.min_box1:
        return False, "min_box1"

    if rule.max_box1 is not None and signal.box_left > rule.max_box1:
        return False, "max_box1"

    if rule.min_box2 is not None and signal.box_right < rule.min_box2:
        return False, "min_box2"

    if rule.max_box2 is not None and signal.box_right > rule.max_box2:
        return False, "max_box2"

    if rule.countries and not _matches_country(signal, rule.countries):
        return False, "country"

    missing_badges = [badge for badge in rule.badges if badge and badge not in text]
    if missing_badges:
        return False, "badge"

    if rule.min_rate is not None and (signal.rate is None or signal.rate < rule.min_rate):
        return False, "min_rate"

    if rule.max_rate is not None and (signal.rate is None or signal.rate > rule.max_rate):
        return False, "max_rate"

    if rule.min_level is not None and (
        signal.level is None or signal.level < rule.min_level
    ):
        return False, "min_level"

    if rule.max_level is not None and (
        signal.level is None or signal.level > rule.max_level
    ):
        return False, "max_level"

    if rule.min_views is not None and (
        signal.views is None or signal.views < rule.min_views
    ):
        return False, "min_views"

    if rule.max_views is not None and (
        signal.views is None or signal.views > rule.max_views
    ):
        return False, "max_views"

    return True, "matched"


def _rule_has_box_constraints(rule: MessageFilterRule) -> bool:
    if rule.boxes:
        return True
    return any(
        value is not None
        for value in (
            rule.min_box1,
            rule.max_box1,
            rule.min_box2,
            rule.max_box2,
            rule.min_rate,
            rule.max_rate,
            rule.min_level,
            rule.max_level,
            rule.min_views,
            rule.max_views,
        )
    )


def _rule_has_signal_constraints(rule: MessageFilterRule) -> bool:
    if _rule_has_box_constraints(rule):
        return True
    if rule.countries or rule.badges:
        return True
    return False


def _rule_has_constraints(rule: MessageFilterRule) -> bool:
    if rule.telegram_groups:
        return True
    if _rule_has_box_constraints(rule):
        return True
    if rule.countries or rule.badges or rule.note_contains or rule.text_contains:
        return True
    if rule.text_regex:
        return True
    return False


def _as_tuple(value: Any) -> Tuple[str, ...]:
    if value in (None, ""):
        return ()
    if isinstance(value, str):
        return tuple(item for item in (_clean_keyword(item) for item in value.split(",")) if item)
    if isinstance(value, list):
        return tuple(item for item in (_clean_keyword(item) for item in value) if item)
    cleaned = _clean_keyword(value)
    return (cleaned,) if cleaned else ()


def _clean_keyword(value: Any) -> str:
    return str(value).strip().strip("'\"").strip()


def _chat_id_aliases(chat_id: str) -> Tuple[str, ...]:
    value = str(chat_id or "").strip()
    if not value:
        return ()
    aliases = [value]
    if value.lstrip("-").isdigit():
        numeric = int(value)
        text = str(numeric)
        if text.startswith("-100") and len(text) > 4:
            aliases.append(str(-int(text[4:])))
        elif numeric < 0:
            aliases.append(f"-100{abs(numeric)}")
        elif numeric > 0:
            aliases.append(f"-100{numeric}")
    return tuple(dict.fromkeys(item for item in aliases if item))


def _chat_matches_groups(
    chat_id: Optional[str],
    chat_label: Optional[str],
    groups: Tuple[str, ...],
) -> bool:
    if not groups:
        return True

    tokens = {_clean_keyword(item).lower() for item in groups if _clean_keyword(item)}
    if not tokens:
        return True

    label = _clean_keyword(chat_label or "").lower()
    if label and label in tokens:
        return True

    for alias in _chat_id_aliases(str(chat_id or "")):
        if alias.lower() in tokens:
            return True

    return False


def _first_present(raw_rule: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in raw_rule and raw_rule[key] not in (None, ""):
            return raw_rule[key]
    return None

def _optional_int(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    return int(value)


def _optional_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    return float(value)


def _normalize_box(value: str) -> str:
    return value.replace(" ", "").strip()


def _matches_country(signal: BoxSignal, raw_countries: Tuple[str, ...]) -> bool:
    allowed_codes = set()
    allowed_flags = set()

    for raw_value in raw_countries:
        value = raw_value.strip()
        if not value:
            continue
        flag = FLAG_RE.fullmatch(value)
        if flag:
            allowed_flags.add(value)
            code = _flag_to_country_code(value)
            if code:
                allowed_codes.add(code)
        else:
            allowed_codes.add(value.upper())

    return bool(
        set(signal.country_codes).intersection(allowed_codes)
        or set(signal.flags).intersection(allowed_flags)
    )


def _flag_to_country_code(flag: str) -> str:
    if len(flag) != 2:
        return ""

    chars = []
    for char in flag:
        codepoint = ord(char)
        if not 0x1F1E6 <= codepoint <= 0x1F1FF:
            return ""
        chars.append(chr(ord("A") + codepoint - 0x1F1E6))
    return "".join(chars)


def _extract_badges(meta: str) -> Tuple[str, ...]:
    text = FLAG_RE.sub("", meta)
    return tuple(char for char in text if char.strip())
