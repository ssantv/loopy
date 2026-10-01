"""Schemas Pydantic de autenticación."""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    """Alta de cuenta adulta.

    No hay cumpleaños aquí: el del niño lo pone el adulto al dar de alta su
    cuenta en `/children`, y el de un adulto no cambia nada (el tono de sus
    avisos no depende de la edad). Se admite `child` en `profile_type` solo
    para poder responder con un error claro en vez de un fallo de validación.
    """

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    profile_type: str = Field(default="adult", pattern="^(adult|child)$")
    display_name: str | None = Field(default=None, max_length=80)
    timezone: str = Field(default="UTC", max_length=64)


class ChildCreateRequest(BaseModel):
    """Perfil de niño creado por una cuenta adulta. Entra con nombre + PIN."""

    display_name: str = Field(min_length=1, max_length=80)
    pin: str = Field(min_length=4, max_length=6, pattern="^[0-9]{4,6}$")
    birth_date: datetime
    course: str | None = Field(default=None, max_length=80)
    timezone: str = Field(default="UTC", max_length=64)


class ChildLoginRequest(BaseModel):
    """Entrada de los menores en su propia cuenta: nombre + PIN."""

    display_name: str = Field(min_length=1, max_length=80)
    pin: str = Field(min_length=4, max_length=6, pattern="^[0-9]{4,6}$")


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    email: EmailStr | None
    profile_type: str
    display_name: str | None
    course: str | None = None
    timezone: str
    notification_tone: str
    tone_source: str
    parent_id: int | None = None
    study_max_minutes: int = 60
    age: int | None
    created_at: datetime


class ProfileUpdate(BaseModel):
    """Edición del perfil. Solo lo que se envía cambia."""

    display_name: str | None = Field(default=None, max_length=80)
    course: str | None = Field(default=None, max_length=80)
    # Tope de minutos de estudio al día. 0 = sin tope (reparto libre).
    study_max_minutes: int | None = Field(default=None, ge=0, le=100000)


class AuthResponse(BaseModel):
    token: str
    user: UserOut


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str = Field(min_length=10, max_length=256)
    new_password: str = Field(min_length=8, max_length=128)