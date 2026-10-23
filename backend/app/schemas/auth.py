from datetime import datetime

from typing import Annotated
from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.services.auth_service import validate_password_bytes

Password = Annotated[str, Field(min_length=6, max_length=128), AfterValidator(validate_password_bytes)]


class RegisterRequest(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: Password


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    created_at: datetime
    is_admin: bool = False
    platform_quota: int = 0
    feishu_bound: bool = False
    feishu_name: str = ""


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
