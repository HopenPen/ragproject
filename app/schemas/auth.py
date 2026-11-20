from typing import Literal
from pydantic import EmailStr, Field, SecretStr
from app.schemas.graphs import Strict


class Login(Strict):
    email: EmailStr
    password: SecretStr


class Refresh(Strict):
    refresh_token: str = Field(min_length=20, max_length=200)


class PasswordChange(Strict):
    old_password: SecretStr
    new_password: SecretStr = Field(min_length=12, max_length=200)


class UserCreate(Strict):
    email: EmailStr
    password: SecretStr = Field(min_length=12, max_length=200)
    display_name: str = Field(default='', max_length=200)
    role: Literal['viewer', 'editor', 'admin']


class UserPatch(Strict):
    display_name: str | None = Field(default=None, max_length=200)
    role: Literal['viewer', 'editor', 'admin'] | None = None
    is_active: bool | None = None
