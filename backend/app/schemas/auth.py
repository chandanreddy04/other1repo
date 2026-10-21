from pydantic import BaseModel


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class TokenPayload(BaseModel):
    sub: str | None = None
    exp: int | None = None
    type: str | None = None
    # Token version — refresh tokens carry the user's token_version at issue
    # time; /refresh rejects the token if the user's version has since been
    # bumped (revoke-all-sessions). Defaults to 0 for tokens issued before this.
    tv: int = 0


class RefreshTokenRequest(BaseModel):
    refresh_token: str
