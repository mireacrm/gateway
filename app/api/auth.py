from fastapi import APIRouter, Depends

from app.api.deps import get_context
from app.api.schemas import TokenOut, TokenRequest
from app.infra.lifespan import AppContext

router = APIRouter(tags=["auth"])


@router.post("/auth/token", response_model=TokenOut)
async def issue_token(payload: TokenRequest, context: AppContext = Depends(get_context)):
    """Логин и пароль в обмен на токен Keycloak.

    Выданный токен тут же проходит обычную проверку: роли в ответе взяты из
    разобранного токена, а не из того, что Keycloak написал рядом.
    """
    grant = await context.keycloak.password_grant(payload.username, payload.password)
    principal = await context.verifier.verify(f"Bearer {grant['access_token']}")
    return TokenOut(
        access_token=grant["access_token"],
        token_type=grant.get("token_type", "Bearer"),
        expires_in=grant.get("expires_in", 0),
        subject=principal.subject,
        username=principal.username,
        roles=sorted(principal.roles),
    )
