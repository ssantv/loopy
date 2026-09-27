"""Autenticación: registro, login, logout y perfil actual."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Session, User
from app.schemas.auth import AuthResponse, LoginRequest, RegisterRequest, UserOut
from app.security import hash_password, verify_password
from app.services.tones import tone_for_age

router = APIRouter(prefix="/api/auth", tags=["auth"])

bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Devuelve el usuario autenticado por token opaco (Authorization: Bearer)."""
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado")
    token_hash = Session.hash_token(credentials.credentials)
    stmt = (
        select(User)
        .join(Session, Session.user_id == User.id)
        .where(Session.token_hash == token_hash, Session.expires_at > datetime.now(UTC))
    )
    user = (await db.execute(stmt)).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sesión inválida o caducada")
    return user


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)) -> AuthResponse:
    existing = (await db.execute(select(User).where(User.email == payload.email))).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ya existe una cuenta con este email")
    # Niño: cumpleaños obligatorio al crear el perfil (para tono automático).
    if payload.profile_type == "child" and payload.birth_date is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="El perfil de niño requiere fecha de nacimiento"
        )
    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        profile_type=payload.profile_type,
        display_name=payload.display_name,
        timezone=payload.timezone,
    )
    # Tono inicial: si hay fecha de nacimiento (niño), se sugiere por edad.
    suggested = tone_for_age(user.age())
    if suggested != user.notification_tone:
        user.notification_tone = suggested
    db.add(user)
    await db.flush()
    token, session = await _create_session(db, user)
    return AuthResponse(token=token, user=UserOut(**user_out_dict(user)))


@router.post("/login", response_model=AuthResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)) -> AuthResponse:
    user = (await db.execute(select(User).where(User.email == payload.email))).scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Email o contraseña incorrectos")
    token, session = await _create_session(db, user)
    return AuthResponse(token=token, user=UserOut(**user_out_dict(user)))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> None:
    await db.execute(Session.__table__.delete().where(Session.user_id == user.id))


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)) -> UserOut:
    # tone_source=auto → el tono se recalcula al cumplir años.
    if user.tone_source == "auto":
        age = user.age()
        if age is not None:
            tone = tone_for_age(age)
            if tone != user.notification_tone:
                user.notification_tone = tone
    return UserOut(**user_out_dict(user))


async def _create_session(db: AsyncSession, user: User) -> tuple[str, Session]:
    token = Session.new_token()
    session = Session(
        user_id=user.id,
        token_hash=Session.hash_token(token),
        expires_at=datetime.now(UTC) + Session.lifetime(),
    )
    db.add(session)
    await db.flush()
    return token, session


def user_out_dict(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "profile_type": user.profile_type,
        "display_name": user.display_name,
        "timezone": user.timezone,
        "notification_tone": user.notification_tone,
        "tone_source": user.tone_source,
        "age": user.age(),
        "created_at": user.created_at,
    }