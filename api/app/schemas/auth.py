"""Schemas Pydantic de autenticación."""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    profile_type: str = Field(default="adult", pattern="^(adult|child)$")
    display_name: str | None = Field(default=None, max_length=80)
    birth_date: datetime | None = Field(default=None, description="Obligatoria para perfil child")
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
    age: int | None
    created_at: datetime


class ProfileUpdate(BaseModel):
    """Edición del perfil. Solo lo que se envía cambia."""

    display_name: str | None = Field(default=None, max_length=80)
    course: str | None = Field(default=None, max_length=80)


class AuthResponse(BaseModel):
    token: str
    user: UserOut


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str = Field(min_length=10, max_length=256)
    new_password: str = Field(min_length=8, max_length=128)