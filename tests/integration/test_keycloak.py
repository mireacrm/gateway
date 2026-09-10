"""Проверка против живого Keycloak.

Юнит-тесты подписывают токены сами и потому доказывают только логику разбора.
Здесь проверяется договорённость с настоящим Keycloak: что realm отдаёт ключи
по ожидаемому адресу, а в токене есть и aud, и роли. Обе вещи ломались на
настройке realm, и обе видны только на живом сервере.
"""

import os
import urllib.error
import urllib.request

import pytest

from app.infra.config import Settings
from app.infra.errors import UnauthenticatedError
from app.security.keycloak import Keycloak
from app.security.tokens import TokenVerifier

ISSUER = os.getenv("GATEWAY_TEST_ISSUER", "http://localhost:8080/realms/mirea")


def _reachable() -> bool:
    try:
        urllib.request.urlopen(f"{ISSUER}/.well-known/openid-configuration", timeout=2)
    except (urllib.error.URLError, OSError):
        return False
    return True


pytestmark = pytest.mark.skipif(not _reachable(), reason=f"Keycloak недоступен: {ISSUER}")


@pytest.fixture
def live_settings() -> Settings:
    return Settings(oidc_issuer=ISSUER)


@pytest.fixture
async def keycloak(live_settings):
    instance = Keycloak(live_settings)
    yield instance
    await instance.close()


@pytest.fixture
def live_verifier(live_settings, keycloak) -> TokenVerifier:
    return TokenVerifier(live_settings, keycloak.keys)


class TestRealm:
    async def test_jwks_published_where_expected(self, keycloak) -> None:
        assert await keycloak.keys.refresh(force=True) is True

    @pytest.mark.parametrize(
        ("username", "password", "role"),
        [
            ("owner", "owner", "admin"),
            ("admin-tverskaya", "manager", "manager"),
        ],
    )
    async def test_roles_reach_the_token(
        self, keycloak, live_verifier, username, password, role
    ) -> None:
        """Без протокол-маппера realm roles ролей в токене не будет вовсе."""
        grant = await keycloak.password_grant(username, password)
        principal = await live_verifier.verify(f"Bearer {grant['access_token']}")
        assert principal.username == username
        assert role in principal.roles

    async def test_audience_present(self, keycloak, live_verifier) -> None:
        """Проверка aud держится на отдельном маппере в realm."""
        grant = await keycloak.password_grant("owner", "owner")
        assert await live_verifier.verify(f"Bearer {grant['access_token']}")

    async def test_wrong_password_rejected(self, keycloak) -> None:
        with pytest.raises(UnauthenticatedError):
            await keycloak.password_grant("owner", "не-тот-пароль")

    async def test_unknown_user_rejected(self, keycloak) -> None:
        with pytest.raises(UnauthenticatedError):
            await keycloak.password_grant("никого-нет", "пароль")
