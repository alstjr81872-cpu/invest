"""Single owner, opaque expiring DB sessions, Argon2id, CSRF + strict Origin."""

import hashlib
import hmac
import secrets
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import Request, HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from .config import settings
from .db import transaction, utcnow
from .models import AuthSession, LoginAttempt

COOKIE_NAME = "invest_session"
HASHER = PasswordHasher()


def digest(token):
    return hmac.new(settings().session_secret.encode(), token.encode(), hashlib.sha256).hexdigest()


def check_origin(origin):
    if origin != settings().origin:
        raise HTTPException(403, "허용되지 않은 요청 출처입니다.")


def login(username, password, client):
    now = utcnow()
    # One private account: the shared owner bucket also limits distributed password guessing.
    bucket = digest("login:owner")
    with transaction() as db:
        db.execute(
            insert(LoginAttempt).values(id=bucket, failures=0, window_start=now).on_conflict_do_nothing()
        )
        attempt = db.scalar(select(LoginAttempt).where(LoginAttempt.id == bucket).with_for_update())
        if now - attempt.window_start > timedelta(minutes=15):
            attempt.failures, attempt.window_start = 0, now
        if attempt.failures >= 5:
            raise HTTPException(429, "로그인 시도가 많습니다. 15분 후 다시 시도하세요.")
        valid = False
        try:
            valid = HASHER.verify(settings().password_hash, password) and hmac.compare_digest(
                username.encode(), settings().owner.encode()
            )
        except (VerificationError, InvalidHashError):
            pass
        if not valid:
            attempt.failures += 1
        else:
            attempt.failures = 0
            token, csrf = secrets.token_urlsafe(48), secrets.token_hex(32)
            db.add(AuthSession(token_hash=digest(token), csrf=csrf, expires_at=now + timedelta(hours=8)))
    # Failed counters must commit before raising an HTTP exception.
    if not valid:
        raise HTTPException(401, "계정 또는 비밀번호를 확인하세요.")
    return token, csrf


def authenticate(token):
    if not token or len(token) > 256:
        return None
    with transaction() as db:
        session = db.get(AuthSession, digest(token))
        if not session or session.revoked or session.expires_at <= utcnow():
            return None
        return {
            "token_hash": session.token_hash,
            "csrf": session.csrf,
            "expires_at": session.expires_at.isoformat(),
        }


def require_owner(request: Request):
    session = authenticate(request.cookies.get(COOKIE_NAME))
    if not session:
        raise HTTPException(401, "로그인이 필요합니다.")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        check_origin(request.headers.get("origin"))
        if not hmac.compare_digest(request.headers.get("x-csrf-token", ""), session["csrf"]):
            raise HTTPException(403, "CSRF 검증에 실패했습니다. 화면을 새로고침하세요.")
    return session
