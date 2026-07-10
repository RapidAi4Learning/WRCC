"""Auth endpoints: cookie-based JWT login + current-user lookup (§4a)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import COOKIE_NAME, get_current_user
from app.auth.rate_limit import login_rate_limit
from app.auth.security import create_access_token, dummy_password_hash, verify_password
from app.config import Settings, get_settings
from app.db.base import get_session
from app.db.models import User

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    id: str
    email: str
    display_name: str


def _to_user_out(user: User) -> UserOut:
    return UserOut(id=str(user.id), email=user.email, display_name=user.display_name)


@router.post("/login", response_model=UserOut, dependencies=[Depends(login_rate_limit)])
async def login(
    body: LoginRequest,
    response: Response,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> UserOut:
    user = (
        await session.execute(select(User).where(User.email == body.email))
    ).scalar_one_or_none()
    # Constant-time failure path: argon2 verification always runs — against a
    # dummy hash when the account is missing or inactive — so an unknown email
    # is not measurably faster than a wrong password (timing oracle).
    password_hash = (
        user.password_hash if user is not None and user.is_active else dummy_password_hash()
    )
    password_ok = verify_password(body.password, password_hash)
    if user is None or not user.is_active or not password_ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password."
        )

    token = create_access_token(user_id=user.id, settings=settings)
    # SameSite=None requires Secure per the browser spec; always Secure in prod.
    secure = settings.app_env == "production" or settings.session_cookie_samesite == "none"
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=secure,
        samesite=settings.session_cookie_samesite,
        domain=settings.session_cookie_domain,
        max_age=settings.jwt_expires_minutes * 60,
    )
    return _to_user_out(user)


@router.post("/logout")
async def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return _to_user_out(user)
