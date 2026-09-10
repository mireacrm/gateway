from datetime import UTC, datetime, timedelta

import pytest

from app.infra.errors import UnauthenticatedError


class TestAcceptedToken:
    async def test_returns_subject_and_roles(self, verifier, issue) -> None:
        principal = await verifier.verify(f"Bearer {issue()}")
        assert principal.username == "owner"
        assert principal.roles == frozenset({"admin"})

    async def test_scheme_is_case_insensitive(self, verifier, issue) -> None:
        assert await verifier.verify(f"bearer {issue()}")

    async def test_user_without_roles_is_authenticated_but_powerless(
        self, verifier, issue
    ) -> None:
        principal = await verifier.verify(f"Bearer {issue(realm_access={'roles': []})}")
        assert principal.roles == frozenset()


class TestRejectedToken:
    @pytest.mark.parametrize(
        ("header", "message"),
        [
            (None, "нет заголовка"),
            ("", "нет заголовка"),
            ("Basic dXNlcjpwYXNz", "схема Bearer"),
            ("Bearer", "схема Bearer"),
            ("Bearer   ", "схема Bearer"),
            ("Bearer не.токен.вовсе", "нечитаем"),
        ],
    )
    async def test_malformed_header(self, verifier, header, message) -> None:
        with pytest.raises(UnauthenticatedError, match=message):
            await verifier.verify(header)

    async def test_expired(self, verifier, issue) -> None:
        past = datetime.now(tz=UTC) - timedelta(hours=1)
        token = issue(iat=past, exp=past + timedelta(minutes=15))
        with pytest.raises(UnauthenticatedError, match="истёк"):
            await verifier.verify(f"Bearer {token}")

    async def test_foreign_realm(self, verifier, issue) -> None:
        with pytest.raises(UnauthenticatedError, match="другим realm"):
            await verifier.verify(f"Bearer {issue(iss='http://evil.test/realms/mirea')}")

    async def test_foreign_audience(self, verifier, issue) -> None:
        with pytest.raises(UnauthenticatedError, match="другого получателя"):
            await verifier.verify(f"Bearer {issue(aud='other-api')}")

    async def test_foreign_client(self, verifier, issue) -> None:
        with pytest.raises(UnauthenticatedError, match="другому клиенту"):
            await verifier.verify(f"Bearer {issue(azp='attacker-app')}")

    async def test_id_token_is_not_an_access_token(self, verifier, issue) -> None:
        """Подпись и realm у ID-токена те же, отличается назначение."""
        with pytest.raises(UnauthenticatedError, match="access-токен"):
            await verifier.verify(f"Bearer {issue(typ='ID')}")

    async def test_unknown_key(self, verifier, issue) -> None:
        with pytest.raises(UnauthenticatedError, match="ключ подписи"):
            await verifier.verify(f"Bearer {issue(kid='rotated-away')}")

    async def test_signature_forged(self, verifier, issue) -> None:
        header, payload, _ = issue().split(".")
        with pytest.raises(UnauthenticatedError, match="подпись"):
            await verifier.verify(f"Bearer {header}.{payload}.bm90LWEtc2lnbmF0dXJl")

    async def test_algorithm_none_rejected(self, verifier, issue) -> None:
        """Классическая атака: подпись выкинута, alg заменён на none."""
        import base64
        import json

        claims = json.dumps({"sub": "attacker", "typ": "Bearer"}).encode()
        encode = lambda raw: base64.urlsafe_b64encode(raw).rstrip(b"=").decode()  # noqa: E731
        header = encode(json.dumps({"alg": "none", "kid": "test-key"}).encode())
        with pytest.raises(UnauthenticatedError):
            await verifier.verify(f"Bearer {header}.{encode(claims)}.")
