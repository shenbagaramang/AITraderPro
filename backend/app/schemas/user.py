from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.config import settings
from app.models.user import UserRole


def _validate_password_strength(value: str) -> str:
    if len(value) < settings.PASSWORD_MIN_LENGTH:
        raise ValueError(
            f"Password must be at least {settings.PASSWORD_MIN_LENGTH} characters"
        )
    if not any(c.isdigit() for c in value):
        raise ValueError("Password must contain at least one digit")
    if not any(c.isalpha() for c in value):
        raise ValueError("Password must contain at least one letter")
    return value


class UserBase(BaseModel):
    email: EmailStr
    full_name: str | None = Field(None, max_length=255)


class UserCreate(UserBase):
    password: str = Field(..., max_length=128)

    _check_password = field_validator("password")(_validate_password_strength)


class UserUpdate(BaseModel):
    full_name: str | None = Field(None, max_length=255)
    email: EmailStr | None = None
    is_active: bool | None = None
    role: UserRole | None = None


class UserPasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(..., max_length=128)

    _check_password = field_validator("new_password")(_validate_password_strength)


class UserPublic(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: UserRole
    is_active: bool
    is_superuser: bool
    is_verified: bool
    last_login_at: datetime | None
    created_at: datetime


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
