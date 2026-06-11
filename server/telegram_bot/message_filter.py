import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

BOX_RE = re.compile(
    r"(?:🎁\s*)?BOX\s*:\s*(?P<left>\d+)\s*/\s*(?P<right>\d+)(?P<tail>.*)",
    re.IGNORECASE | re.DOTALL,
)
RATE_RE = re.compile(r"📈\s*Rate\s*:\s*(?P<rate>\d+(?:\.\d+)?)", re.IGNORECASE)
VIEWS_RE = re.compile(r"👀\s*(?P<views>\d+)")
NOTE_RE = re.compile(r"📝\s*(?P<note>.+)$", re.DOTALL)
FLAG_RE = re.compile(r"[\U0001F1E6-\U0001F1FF]{2}")


@dataclass(frozen=True)
class BoxSignal:
    box: str
    box_left: int
    box_right: int
    rate: Optional[float]
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
    min_views: Optional[int]
    max_views: Optional[int]
    note_contains: Tuple[str, ...]
    text_contains: Tuple[str, ...]
    text_regex: Optional[str]
    order: int

    def priority_or(self, default_priority: int) -> int:
        return self.priority if self.priority is not None else default_priority

    def to_payload(self, default_priority: int) -> Dict[str, Any]:
        return {
            "name": self.name,
            "priority": self.priority_or(default_priority),
        }


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

    def evaluate(
        self,
        text: str,
        signal: Optional[BoxSignal] = None,
    ) -> FilterResult:
        signal = signal or parse_box_signal(text)
        if not self.enabled:
            return FilterResult(True, "disabled", signal, None, self.default_priority)

        self._reload_if_needed()
        enabled_rules = [rule for rule in self._rules if rule.enabled]
        if not enabled_rules:
            return FilterResult(True, "no_enabled_filters", signal, None, self.default_priority)

        matched_rules = []
        last_reason = "not_matched"
        for rule in enabled_rules:
            matched, reason = _evaluate_rule(text, signal, rule)
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
            if self._rules:
                logger.warning("Message filter config missing path=%s", self.config_path)
            self._rules = ()
            self._last_mtime = None
            return

        if self._last_mtime == mtime:
            return

        self._last_mtime = mtime
        self._rules = tuple(_load_rules(self.config_path))
        enabled_count = sum(1 for rule in self._rules if rule.enabled)
        logger.info(
            "Loaded message filters path=%s total=%s enabled=%s",
            self.config_path,
            len(self._rules),
            enabled_count,
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
        views=int(views_match.group("views")) if views_match else None,
        flags=flags,
        country_codes=country_codes,
        badges=_extract_badges(meta),
        note=(note_match.group("note").strip() if note_match else ""),
    )


def _load_rules(path: Path) -> List[MessageFilterRule]:
    with path.open(encoding="utf-8") as file:
        raw_config = json.load(file)

    raw_rules = raw_config.get("filters", raw_config) if isinstance(raw_config, dict) else raw_config
    if not isinstance(raw_rules, list):
        raise RuntimeError("message filter config must be a list or object with filters=[]")

    return [_parse_rule(raw_rule, index) for index, raw_rule in enumerate(raw_rules)]


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
        min_views=_optional_int(raw_rule.get("min_views")),
        max_views=_optional_int(raw_rule.get("max_views")),
        note_contains=_as_tuple(raw_rule.get("note_contains")),
        text_contains=_as_tuple(raw_rule.get("text_contains")),
        text_regex=(
            str(raw_rule.get("text_regex")).strip()
            if raw_rule.get("text_regex") not in (None, "")
            else None
        ),
        order=index,
    )


def _evaluate_rule(
    text: str,
    signal: Optional[BoxSignal],
    rule: MessageFilterRule,
) -> Tuple[bool, str]:
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

    if rule.min_views is not None and (
        signal.views is None or signal.views < rule.min_views
    ):
        return False, "min_views"

    if rule.max_views is not None and (
        signal.views is None or signal.views > rule.max_views
    ):
        return False, "max_views"

    lowered_text = text.lower()
    missing_notes = [
        value for value in rule.note_contains if value and value.lower() not in lowered_text
    ]
    if missing_notes:
        return False, "note"

    missing_text = [
        value for value in rule.text_contains if value and value.lower() not in lowered_text
    ]
    if missing_text:
        return False, "text"

    if rule.text_regex and not re.search(rule.text_regex, text, re.IGNORECASE):
        return False, "regex"

    return True, "matched"


def _as_tuple(value: Any) -> Tuple[str, ...]:
    if value in (None, ""):
        return ()
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return (str(value).strip(),)


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
