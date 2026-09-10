import json
from datetime import UTC
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.infra.config import Settings
from app.infra.lifespan import AppContext
from app.main import create_app
from app.routing.matcher import Router
from app.routing.proxy import Proxy
from app.security.tokens import TokenVerifier

KID = "test-key"
SUBJECT = "8f1c0e4e-0000-4000-8000-000000000001"
EMPLOYEE_ID = "3a7c9d21-0000-4000-8000-0000000000aa"
ISSUER = "http://keycloak.test/realms/mirea"
AUDIENCE = "mirea-api"
CLIENT_ID = "mirea-web"


class StubKeyStore:
    """Подменяет JWKS: ключ известен один и заранее."""

    def __init__(self, public_key: Any) -> None:
        self._public_key = public_key
        self.loaded = True

    async def key(self, kid: str) -> Any | None:
        return self._public_key if kid == KID else None

    async def refresh(self, force: bool = False) -> bool:
        return True


@pytest.fixture(scope="session")
def keypair():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private, private.public_key()


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(
        oidc_issuer=ISSUER,
        oidc_audience=AUDIENCE,
        oidc_client_id=CLIENT_ID,
        clock_skew=0,
    )


@pytest.fixture
def verifier(settings, keypair) -> TokenVerifier:
    return TokenVerifier(settings, StubKeyStore(keypair[1]))


@pytest.fixture
def issue(keypair):
    """Выпускает токен: по умолчанию корректный, по аргументам — какой угодно."""
    private = keypair[0]

    def factory(**overrides) -> str:
        from datetime import datetime, timedelta

        now = datetime.now(tz=UTC)
        claims: dict[str, Any] = {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "azp": CLIENT_ID,
            "typ": "Bearer",
            "sub": SUBJECT,
            "preferred_username": "owner",
            "realm_access": {"roles": ["admin"]},
            "iat": now,
            "exp": now + timedelta(minutes=15),
        }
        headers = {"kid": overrides.pop("kid", KID)}
        claims.update(overrides)
        claims = {key: value for key, value in claims.items() if value is not None}
        return jwt.encode(claims, private, algorithm="RS256", headers=headers)

    return factory


class StubEmployees:
    """Подменяет справочник сотрудников и запоминает обращения."""

    def __init__(self, mapping: dict[str, str] | None = None) -> None:
        self.mapping = mapping or {}
        self.lookups: list[str] = []

    async def employee_id(self, subject: str) -> str:
        self.lookups.append(subject)
        return self.mapping.get(subject, "")

    async def close(self) -> None:
        pass


class RecordingUpstream:
    """Заглушка соседа: запоминает, что до него доехало."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(
            200,
            json={"path": request.url.path, "headers": dict(request.headers)},
        )

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]

    def last_body(self) -> dict:
        return json.loads(self.requests[-1].content or b"{}")


@pytest.fixture
def upstream() -> RecordingUpstream:
    return RecordingUpstream()


@pytest.fixture
def employees() -> StubEmployees:
    return StubEmployees({SUBJECT: EMPLOYEE_ID})


@pytest.fixture
def app(settings, verifier, upstream, employees):
    transport = httpx.MockTransport(upstream.handler)
    proxy = Proxy(
        settings.upstreams(),
        client=httpx.AsyncClient(transport=transport),
    )
    context = AppContext(
        settings=settings,
        keycloak=None,
        verifier=verifier,
        router=Router(),
        proxy=proxy,
        employees=employees,
    )
    return create_app(context)


@pytest.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as instance:
        yield instance
