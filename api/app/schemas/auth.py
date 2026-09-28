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


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    email: EmailStr
    profile_type: str
    display_name: str | None
    course: str | None = None
    timezone: str
    notification_tone: str
    tone_source: str
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