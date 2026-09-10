"""Обращения к Keycloak: ключи и выдача токена по логину и паролю."""

import httpx

from app.infra.config import Settings
from app.infra.errors import UnauthenticatedError, UpstreamUnavailableError
from app.security.jwks import KeyStore


class Keycloak:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(timeout=5.0)
        self.keys = KeyStore(settings.jwks_url, settings.jwks_cooldown, client=self._client)

    async def password_grant(self, username: str, password: str) -> dict:
        """Обмен пароля на токен.

        В боевой системе так не делают: браузер идёт в Keycloak сам по
        authorization code с PKCE и пароль до шлюза не доходит. Здесь ручка
        нужна, чтобы получить токен из curl и не поднимать фронтенд.
        """
        try:
            response = await self._client.post(
                self._settings.token_url,
                data={
                    "grant_type": "password",
                    "client_id": self._settings.oidc_client_id,
                    "username": username,
                    "password": password,
                },
            )
        except httpx.HTTPError as exc:
            raise UpstreamUnavailableError("keycloak") from exc

        if response.status_code == httpx.codes.UNAUTHORIZED:
            raise UnauthenticatedError("неверный логин или пароль")
        if response.status_code >= httpx.codes.BAD_REQUEST:
            detail = response.json().get("error_description", response.text)
            raise UnauthenticatedError(f"Keycloak отказал: {detail}")
        return response.json()

    async def close(self) -> None:
        await self._client.aclose()
