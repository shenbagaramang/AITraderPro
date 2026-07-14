from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_at: datetime


class TokenPayload(BaseModel):
    sub: str
    type: str
    jti: str
    exp: int
    iat: int


class RefreshRequest(BaseModel):
    refresh_token: str
