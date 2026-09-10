"""Проверка access-токена Keycloak.

Проверяется всё, что делает токен именно этим токеном: подпись ключом realm,
срок, издатель, получатель и клиент, которому он выдан. Пропуск любого из
пунктов делает проверку декоративной.
"""

import logging

import jwt

from app.infra.config import Settings
from app.infra.errors import UnauthenticatedError
from app.security.jwks import KeyStore
from app.security.principal import Principal

log = logging.getLogger(__name__)

_SCHEME = "bearer"


class TokenVerifier:
    def __init__(self, settings: Settings, keys: KeyStore) -> None:
        self._settings = settings
        self._keys = keys

    async def verify(self, authorization: str | None) -> Principal:
        token = _extract(authorization)
        claims = await self._decode(token)
        return _principal(claims)

    async def _decode(self, token: str) -> dict:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError as exc:
            raise UnauthenticatedError("токен нечитаем") from exc

        kid = header.get("kid")
        if not kid:
            raise UnauthenticatedError("в заголовке токена нет kid")

        key = await self._keys.key(kid)
        if key is None:
            raise UnauthenticatedError("ключ подписи неизвестен")

        settings = self._settings
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=list(settings.oidc_algorithms),
                audience=settings.oidc_audience,
                issuer=settings.oidc_issuer,
                leeway=settings.clock_skew,
                options={"require": ["exp", "iat", "iss", "sub", "aud"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise UnauthenticatedError("срок действия токена истёк") from exc
        except jwt.InvalidAudienceError as exc:
            raise UnauthenticatedError("токен выдан для другого получателя") from exc
        except jwt.InvalidIssuerError as exc:
            raise UnauthenticatedError("токен выдан другим realm") from exc
        except jwt.InvalidTokenError as exc:
            raise UnauthenticatedError("подпись токена неверна") from exc

        # Без этой пары проверок ID-токен или токен чужого клиента прошёл бы
        # как обычный access-токен: подпись и realm у них те же самые.
        if claims.get("typ") != "Bearer":
            raise UnauthenticatedError("нужен access-токен")
        expected_client = settings.oidc_client_id
        if expected_client and claims.get("azp") != expected_client:
            raise UnauthenticatedError("токен выдан другому клиенту")
        return claims


def _extract(authorization: str | None) -> str:
    if not authorization:
        raise UnauthenticatedError("нет заголовка Authorization")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != _SCHEME or not token.strip():
        raise UnauthenticatedError("ожидается схема Bearer")
    return token.strip()


def _principal(claims: dict) -> Principal:
    roles = claims.get("realm_access", {}).get("roles", [])
    return Principal(
        subject=claims["sub"],
        username=claims.get("preferred_username", ""),
        roles=frozenset(str(role) for role in roles),
    )
