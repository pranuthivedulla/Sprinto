"""Passcode gate for the review page.

The page lists real people's names, titles and email addresses, so once it is on a
public URL it has to be closed to everyone but the reviewer. One shared passcode is
not real authentication; it is a locked door, and the throttle is what stops someone
trying every key.

No passcode ever appears in a URL. The cookie carries a signed timestamp, nothing else.
"""
import hashlib
import hmac
import os
import time
from datetime import datetime, timedelta, timezone

from . import config, db

COOKIE_NAME = "sprinto_review"
# Local runs without SESSION_SECRET get a per-process key: sessions end on restart,
# which is fine on a laptop and never happens in production, where the real key is set.
_FALLBACK_SECRET = os.urandom(32).hex()


def secret():
    return config.get("SESSION_SECRET") or _FALLBACK_SECRET


def _sign(payload):
    return hmac.new(secret().encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]


def make_token():
    payload = str(int(time.time()))
    return f"{payload}.{_sign(payload)}"


def token_ok(token):
    payload, _, signature = (token or "").partition(".")
    if not payload.isdigit() or not signature:
        return False
    if not hmac.compare_digest(signature, _sign(payload)):
        return False
    return (time.time() - int(payload)) < config.SESSION_MAX_AGE


def passcode_ok(given):
    expected = config.get("REVIEW_PASSCODE")
    return bool(expected) and hmac.compare_digest(str(given), expected)


def client_ip(request):
    """Vercel puts the real client first in x-forwarded-for."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return getattr(request.client, "host", "") or "unknown"


def _window_start():
    start = datetime.now(timezone.utc) - timedelta(seconds=config.LOGIN_WINDOW_SECONDS)
    return start.strftime("%Y-%m-%d %H:%M:%S")


def throttled(ip):
    return db.recent_login_failures(ip, _window_start()) >= config.LOGIN_MAX_FAILURES


def record_failure(ip):
    db.record_login_failure(ip)


def clear_failures(ip):
    db.clear_login_failures(ip)


def authorized(request, passcode_field=""):
    """A valid session cookie, or the passcode supplied directly.

    The cookie is SameSite=Lax, so another site cannot post to these endpoints
    with it attached.
    """
    if token_ok(request.cookies.get(COOKIE_NAME)):
        return True
    return passcode_ok(passcode_field)


def set_cookie(response):
    response.set_cookie(
        COOKIE_NAME,
        make_token(),
        max_age=config.SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=config.is_production(),
        path="/",
    )
    return response
