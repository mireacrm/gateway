from pydantic import BaseModel, Field


class TokenRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class TokenOut(BaseModel):
    access_token: str
    token_type: str
    expires_in: int
    subject: str
    username: str
    roles: list[str]


class RouteOut(BaseModel):
    method: str
    path: str
    upstream: str
    roles: list[str]
    summary: str
