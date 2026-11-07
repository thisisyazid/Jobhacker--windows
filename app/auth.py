"""One shared app password → long-lived signed cookie. Works nicely with a
phone home-screen app (unlike HTTP Basic Auth). Automations use X-API-Key."""
import hashlib
import hmac
import secrets
import time

from fastapi import Request

from . import config

COOKIE = "jh_session"


def _sign(payload: str) -> str:
    return hmac.new(config.SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_token() -> str:
    exp = int(time.time()) + config.SESSION_DAYS * 86400
    payload = f"{exp}.{secrets.token_hex(8)}"
    return f"{payload}.{_sign(payload)}"


def valid_token(tok: str | None) -> bool:
    if not tok or tok.count(".") != 2:
        return False
    exp, nonce, sig = tok.split(".")
    if not hmac.compare_digest(sig, _sign(f"{exp}.{nonce}")):
        return False
    try:
        return int(exp) > time.time()
    except ValueError:
        return False


def check_password(pw: str) -> bool:
    return bool(config.APP_PASSWORD) and hmac.compare_digest(pw.encode(), config.APP_PASSWORD.encode())


def via_api_token(request: Request) -> bool:
    tok = request.headers.get("x-api-key") or request.query_params.get("key")
    return bool(config.API_TOKEN) and bool(tok) and hmac.compare_digest(tok, config.API_TOKEN)


def is_authed(request: Request) -> bool:
    if not config.APP_PASSWORD:
        return True
    return valid_token(request.cookies.get(COOKIE)) or via_api_token(request)


def cookie_secure(request: Request) -> bool:
    if config.COOKIE_SECURE == "true":
        return True
    if config.COOKIE_SECURE == "false":
        return False
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    return proto == "https"
