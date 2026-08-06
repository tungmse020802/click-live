import hashlib
import hmac
import secrets
import time
from pathlib import Path
from typing import Optional

from config import QueueUiConfig, queue_users_map
from desktop_auth import verify_queue_user


SESSION_COOKIE = "queue_ui_session"
SESSION_TTL_SECONDS = 7 * 24 * 3600
PUBLIC_PATHS = frozenset({"/login"})


def auth_secret_path(base_dir: Path) -> Path:
    return base_dir / "data" / "queue_ui_auth.secret"


def load_or_create_auth_secret(base_dir: Path, auth_enabled: bool) -> str:
    path = auth_secret_path(base_dir)
    if path.exists():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value

    if not auth_enabled:
        return ""

    path.parent.mkdir(parents=True, exist_ok=True)
    value = secrets.token_hex(32)
    path.write_text(value + "\n", encoding="utf-8")
    return value


def verify_credentials(username: str, password: str, config: QueueUiConfig) -> bool:
    if not config.auth_enabled:
        return True
    users = queue_users_map(config)
    if users:
        return verify_queue_user(username, password, users)
    return hmac.compare_digest(username, config.auth_username) and hmac.compare_digest(
        password, config.auth_password
    )


def create_session_token(secret: str, username: str = "") -> str:
    expires = int(time.time()) + SESSION_TTL_SECONDS
    user = str(username or "").strip()
    payload = f"{expires}:{user}" if user else str(expires)
    signature = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def _session_payload(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    parts = token.split(".", 1)
    if len(parts) != 2:
        return None
    return parts[0]


def verify_session_token(token: Optional[str], secret: str) -> bool:
    if not secret or not token:
        return False

    payload = _session_payload(token)
    if payload is None:
        return False
    signature = token.split(".", 1)[1]
    expected = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return False

    expires_text = payload.split(":", 1)[0]
    try:
        expires = int(expires_text)
    except ValueError:
        return False

    return expires >= int(time.time())


def session_username_from_token(token: Optional[str], config: QueueUiConfig) -> Optional[str]:
    if not verify_session_token(token, config.auth_secret):
        return None
    payload = _session_payload(token)
    if payload and ":" in payload:
        return payload.split(":", 1)[1].strip() or None
    if config.auth_username:
        return config.auth_username
    users = getattr(config, "queue_users", None) or {}
    if len(users) == 1:
        return next(iter(users))
    return None


def is_authenticated(cookie_value: Optional[str], config: QueueUiConfig) -> bool:
    if not config.auth_enabled:
        return True
    return verify_session_token(cookie_value, config.auth_secret)


def parse_cookie_header(header_value: str, name: str) -> Optional[str]:
    if not header_value:
        return None

    prefix = f"{name}="
    for part in header_value.split(";"):
        part = part.strip()
        if part.startswith(prefix):
            return part[len(prefix) :]
    return None


LOGIN_HTML = r"""<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <title>Đăng nhập — Telegram Bot Panel</title>
  <style>
    :root { --bg:#f5f6f8; --surface:#fff; --border:#d7dce2; --text:#20242a; --muted:#66707b; --blue:#1d5fd0; --red:#b42318; }
    * { box-sizing:border-box; }
    body { margin:0; min-height:100vh; display:grid; place-items:center; background:var(--bg); color:var(--text); font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; padding:max(16px, env(safe-area-inset-top)) 16px max(16px, env(safe-area-inset-bottom)); }
    .card { width:min(420px, 100%); background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:28px 22px; box-shadow:0 8px 24px rgba(20,28,38,.08); }
    h1 { margin:0 0 8px; font-size:22px; }
    p { margin:0 0 20px; color:var(--muted); font-size:14px; line-height:1.5; }
    label { display:block; margin:14px 0 6px; color:var(--muted); font-size:12px; font-weight:700; text-transform:uppercase; }
    input { width:100%; border:1px solid var(--border); border-radius:8px; padding:11px 12px; font:inherit; }
    button { width:100%; margin-top:18px; min-height:42px; border:0; border-radius:8px; background:var(--blue); color:#fff; font:inherit; font-weight:700; cursor:pointer; }
    button:hover { filter:brightness(1.05); }
    .error { margin-top:14px; padding:10px 12px; border:1px solid #f5b6ad; background:#fff0ee; color:var(--red); border-radius:8px; font-size:13px; display:none; }
    .error.show { display:block; }
  </style>
</head>
<body>
  <form class="card" id="loginForm">
    <h1>Telegram Bot Panel</h1>
    <p>Đăng nhập để quản lý hàng đợi tin nhắn, filter, nhóm theo dõi và broadcast.</p>
    <label for="username">Tên đăng nhập</label>
    <input id="username" name="username" autocomplete="username" required>
    <label for="password">Mật khẩu</label>
    <input id="password" name="password" type="password" autocomplete="current-password" required>
    <button type="submit">Đăng nhập</button>
    <div id="error" class="error"></div>
  </form>
  <script>
    const params = new URLSearchParams(location.search);
    const next = params.get('next') || '/';
    document.getElementById('loginForm').addEventListener('submit', async (event) => {
      event.preventDefault();
      const error = document.getElementById('error');
      error.classList.remove('show');
      const body = {
        username: document.getElementById('username').value.trim(),
        password: document.getElementById('password').value
      };
      try {
        const res = await fetch('/api/auth/login', {
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify(body)
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Đăng nhập thất bại');
        location.href = next.startsWith('/') ? next : '/';
      } catch (err) {
        error.textContent = err.message;
        error.classList.add('show');
      }
    });
  </script>
</body>
</html>
"""

LOGOUT_SCRIPT = r"""
function bindLogout(){
  const btn = document.getElementById('logoutBtn');
  if (!btn) return;
  btn.addEventListener('click', () => {
    fetch('/api/auth/logout', { method:'POST' }).finally(() => { location.href = '/login'; });
  });
}
bindLogout();
"""

