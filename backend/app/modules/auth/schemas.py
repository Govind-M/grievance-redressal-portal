from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.modules.users.schemas import UserResponse, normalize_email, validate_mobile, validate_name


class RegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(max_length=150)
    email: str = Field(max_length=255)
    mobile_number: str = Field(max_length=15)
    password: SecretStr = Field(min_length=12, max_length=128)

    _name = field_validator("name")(validate_name)
    _email = field_validator("email")(normalize_email)
    _mobile = field_validator("mobile_number")(validate_mobile)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=255)
    password: SecretStr = Field(min_length=1, max_length=128)

    _email = field_validator("email")(normalize_email)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    csrf_token: str
    user: UserResponse
