"""Autenticación: registro, login, logout y perfil actual."""

import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.models import PasswordResetToken, Session, User
from app.schemas.auth import (
    AuthResponse,
    ChildCreateRequest,
    ChildLoginRequest,
    LoginRequest,
    PasswordResetConfirm,
    PasswordResetRequest,
    ProfileUpdate,
    RegisterRequest,
    UserOut,
)
from app.security import hash_password, verify_password
from app.services.mailer import password_reset_body, send_email
from app.services.ratelimit import SlidingWindowLimiter
from app.services.tones import tone_for_age

router = APIRouter(prefix="/api/auth", tags=["auth"])

bearer = HTTPBearer(auto_error=False)

# Fuerza bruta: 5 intentos fallidos por (email, IP) en una ventana de 5 min.
_login_limiter = SlidingWindowLimiter(settings.login_max_attempts, settings.login_window_seconds)
# Lo mismo para el PIN de los niños: un PIN corto (4-6 dígitos) hace el límite
# de intentos más importante que en email porque es trivial de inventar.
_pin_limiter = SlidingWindowLimiter(settings.login_max_attempts, settings.login_window_seconds)
# Peticiones de reset: 3 por (email, IP) en la misma ventana, para no spamear
# correos a un tercero que sepa el email de alguien.
_reset_limiter = SlidingWindowLimiter(settings.password_reset_max_requests, settings.login_window_seconds)


def _login_key(request: Request, email: str) -> str:
    """Clave del limitador. Usa el email normalizado y la IP del cliente.

    Detrás de un proxy (Caddy/nginx) `request.client.host` es la IP del proxy;
    por eso se prioriza X-Forwarded-For cuando viene, que es lo que inyecta
    Caddy en el despliegue real.
    """
    forwarded = request.headers.get("x-forwarded-for")
    ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown")
    return f"{email.lower()}|{ip}"


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
        birth_date=payload.birth_date,
    )
    # Tono inicial: si hay fecha de nacimiento (niño), se sugiere por edad.
    suggested = tone_for_age(user.age())
    if suggested != user.notification_tone:
        user.notification_tone = suggested
    db.add(user)
    await db.flush()
    token, session = await _create_session(db, user)
    return AuthResponse(token=token, user=UserOut(**user_out_dict(user)))


@router.post("/children", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_child(
    payload: ChildCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserOut:
    """Crea un perfil de niño vinculado a la cuenta adulta que lo abre.

    Los menores no tienen email propio: entran con nombre + PIN. El adulto
    guarda en `parent_id` quién creó la cuenta, y el `birth_date` se usa para
    sugerir el tono de notificación por edad.
    """
    if user.profile_type != "adult":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Solo el perfil adulto puede crear cuentas de niño"
        )
    child = User(
        # Sin email: la entrada es nombre + PIN. El hash de contraseña es
        # basura inutilizable: nunca se loguea por contraseña.
        password_hash=hash_password(secrets.token_urlsafe(48)),
        profile_type="child",
        display_name=payload.display_name,
        course=payload.course,
        timezone=payload.timezone,
        parent_id=user.id,
        pin_hash=hash_password(payload.pin),
        birth_date=payload.birth_date,
    )
    # Tono inicial: sugerido por edad (misma lógica que el registro).
    suggested = tone_for_age(child.age())
    if suggested != child.notification_tone:
        child.notification_tone = suggested
    db.add(child)
    await db.commit()
    await db.refresh(child)
    return UserOut(**user_out_dict(child))


@router.post("/child-login", response_model=AuthResponse)
async def child_login(
    payload: ChildLoginRequest, request: Request, db: AsyncSession = Depends(get_db)
) -> AuthResponse:
    """Entrada de los menores en su cuenta: nombre + PIN (sin email)."""
    key = _login_key(request, payload.display_name)
    retry_after = _pin_limiter.retry_after(key)
    if retry_after:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Demasiados intentos fallidos. Inténtalo de nuevo en {retry_after} s.",
            headers={"Retry-After": str(retry_after)},
        )
    matches = (
        await db.execute(
            select(User).where(
                User.profile_type == "child",
                User.display_name == payload.display_name,
                User.pin_hash.is_not(None),
            )
        )
    ).scalars().all()
    # Un nombre puede repetirse: solo entra si exactamente una cuenta coincide
    # con el PIN. Dos coincidencias se tratan como fallo, no se decide por uno.
    verified = [candidate for candidate in matches if verify_password(payload.pin, candidate.pin_hash)]
    if len(verified) != 1:
        _pin_limiter.record_failure(key)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Nombre o PIN incorrectos")
    # Login correcto: el contador de esa clave se olvida.
    _pin_limiter.reset(key)
    token, session = await _create_session(db, verified[0])
    return AuthResponse(token=token, user=UserOut(**user_out_dict(verified[0])))


@router.post("/login", response_model=AuthResponse)
async def login(
    payload: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)
) -> AuthResponse:
    key = _login_key(request, payload.email)
    retry_after = _login_limiter.retry_after(key)
    if retry_after:
        # 429 Too Many Requests + Retry-After: el cliente sabe cuándo reintentar.
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Demasiados intentos fallidos. Inténtalo de nuevo en {retry_after} s.",
            headers={"Retry-After": str(retry_after)},
        )
    user = (await db.execute(select(User).where(User.email == payload.email))).scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        _login_limiter.record_failure(key)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Email o contraseña incorrectos")
    # Login correcto: el contador de esa clave se olvida.
    _login_limiter.reset(key)
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


@router.patch("/me", response_model=UserOut)
async def update_me(
    payload: ProfileUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> UserOut:
    """Actualiza el perfil (nombre, curso). Solo cambia lo que viene informado."""
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(user, k, v)
    await db.commit()
    await db.refresh(user)
    return UserOut(**user_out_dict(user))


@router.post("/password-reset/request", status_code=status.HTTP_202_ACCEPTED)
async def request_password_reset(
    payload: PasswordResetRequest, request: Request, db: AsyncSession = Depends(get_db)
) -> dict:
    """Pide un enlace de reset. Siempre responde 202, exista o no la cuenta.

    Responder distinto según el email exista sería enumerar las cuentas del
    sistema, así que el cliente recibe siempre el mismo mensaje.
    """
    key = f"reset:{_login_key(request, payload.email)}"
    retry_after = _reset_limiter.retry_after(key)
    if retry_after:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Has pedido demasiados resets. Inténtalo de nuevo en {retry_after} s.",
            headers={"Retry-After": str(retry_after)},
        )
    generic = {"detail": "Si el email existe, te hemos enviado un enlace para restablecer la contraseña."}
    user = (await db.execute(select(User).where(User.email == payload.email))).scalar_one_or_none()
    if user is None:
        return generic

    # Invalida los tokens anteriores vivos de esa cuenta: solo uno sirve.
    await db.execute(
        PasswordResetToken.__table__.update()
        .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
        .values(used_at=datetime.now(UTC))
    )
    token = PasswordResetToken.new_token()
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=PasswordResetToken.hash_token(token),
            expires_at=datetime.now(UTC) + PasswordResetToken.lifetime(),
        )
    )
    await db.flush()
    minutes = settings.password_reset_ttl_minutes
    link = f"{settings.public_app_url.rstrip('/')}/reset-password?token={token}"
    subject, body = password_reset_body(link, minutes)
    await send_email(user.email, subject, body)
    _reset_limiter.record_failure(key)
    return generic


@router.post("/password-reset/confirm")
async def confirm_password_reset(payload: PasswordResetConfirm, db: AsyncSession = Depends(get_db)) -> dict:
    """Canjea el token, cambia la contraseña y revoca las sesiones del usuario."""
    stmt = select(PasswordResetToken).where(
        PasswordResetToken.token_hash == PasswordResetToken.hash_token(payload.token)
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    # Mismo mensaje para token inexistente, ya usado o caducado: no damos pistas.
    invalid = {"detail": "El enlace no es válido o ha caducado. Pide uno nuevo."}
    if row is None or not row.is_usable():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, **invalid)

    user = (await db.execute(select(User).where(User.id == row.user_id))).scalar_one()
    user.password_hash = hash_password(payload.new_password)
    row.used_at = datetime.now(UTC)
    # Si la contraseña se filtra, las sesiones vivas también deben caer.
    await db.execute(Session.__table__.delete().where(Session.user_id == user.id))
    # Los tokens ya canjeados no sirven de nada: se limpian los que sigan vivos.
    await db.execute(
        PasswordResetToken.__table__.update()
        .where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
        .values(used_at=datetime.now(UTC))
    )
    return {"detail": "Contraseña actualizada. Ya puedes iniciar sesión."}


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
        "course": user.course,
        "timezone": user.timezone,
        "notification_tone": user.notification_tone,
        "tone_source": user.tone_source,
        "parent_id": user.parent_id,
        "age": user.age(),
        "created_at": user.created_at,
    }