"""Поведение шлюза целиком: от заголовка Authorization до запроса к соседу."""

import httpx
import pytest

from app.routing.proxy import Proxy
from app.security.principal import (
    HEADER_EMPLOYEE,
    HEADER_ROLES,
    HEADER_SUBJECT,
    HEADER_USERNAME,
)
from tests.conftest import EMPLOYEE_ID, SUBJECT, StubEmployees


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TestAccess:
    async def test_no_token_rejected(self, client, upstream) -> None:
        response = await client.get("/templates")
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        assert not upstream.requests, "запрос не должен доходить до сервиса"

    async def test_role_checked_before_proxying(self, client, issue, upstream) -> None:
        token = issue(realm_access={"roles": ["specialist"]})
        response = await client.get("/clients", headers=auth(token))
        assert response.status_code == 403
        assert not upstream.requests

    async def test_allowed_role_passes(self, client, issue) -> None:
        token = issue(realm_access={"roles": ["manager"]})
        assert (await client.get("/clients", headers=auth(token))).status_code == 200

    async def test_unknown_route_is_404_without_token(self, client) -> None:
        assert (await client.get("/wat")).status_code == 404

    async def test_wrong_method_lists_allowed(self, client, issue) -> None:
        response = await client.delete("/companies", headers=auth(issue()))
        assert response.status_code == 405
        assert response.headers["allow"] == "POST"


class TestForwarding:
    async def test_identity_reaches_upstream(self, client, issue, upstream) -> None:
        await client.get("/templates", headers=auth(issue()))
        headers = upstream.last.headers
        assert headers[HEADER_SUBJECT] == SUBJECT
        assert headers[HEADER_USERNAME] == "owner"
        assert headers[HEADER_ROLES] == "admin"

    async def test_forged_identity_is_overwritten(self, client, issue, upstream) -> None:
        """Заголовки личности выставляет только шлюз, иначе их подделает любой."""
        headers = auth(issue()) | {
            HEADER_SUBJECT: "00000000-dead-4000-8000-000000000000",
            HEADER_ROLES: "admin,manager,specialist",
        }
        await client.get("/templates", headers=headers)
        assert upstream.last.headers[HEADER_SUBJECT] == SUBJECT
        assert upstream.last.headers[HEADER_ROLES] == "admin"

    async def test_token_does_not_travel_further(self, client, issue, upstream) -> None:
        await client.get("/templates", headers=auth(issue()))
        assert "authorization" not in upstream.last.headers

    async def test_cyrillic_username_survives(self, client, issue, upstream) -> None:
        """В заголовок HTTP пролезает только ASCII, поэтому имя кодируется."""
        await client.get("/templates", headers=auth(issue(preferred_username="Ольга")))
        assert upstream.last.headers[HEADER_USERNAME] == "%D0%9E%D0%BB%D1%8C%D0%B3%D0%B0"

    async def test_query_and_body_preserved(self, client, issue, upstream) -> None:
        await client.post(
            "/clients?source=phone", headers=auth(issue()), json={"phone": "+79990000000"}
        )
        assert upstream.last.url.params["source"] == "phone"
        assert upstream.last_body() == {"phone": "+79990000000"}

    async def test_employee_reaches_upstream(self, client, issue, upstream) -> None:
        """Сервису-владельцу нужен сотрудник, иначе сравнивать не с чем."""
        token = issue(realm_access={"roles": ["specialist"]})
        await client.get("/templates", headers=auth(token))
        assert upstream.last.headers[HEADER_EMPLOYEE] == EMPLOYEE_ID

    async def test_unlinked_account_gets_empty_employee(
        self, client, issue, upstream, employees
    ) -> None:
        """Учётной записи может не соответствовать сотрудник — это не ошибка."""
        employees.mapping.clear()
        token = issue(realm_access={"roles": ["specialist"]})
        await client.get("/templates", headers=auth(token))
        assert upstream.last.headers[HEADER_EMPLOYEE] == ""

    async def test_privileged_caller_is_not_resolved(
        self, client, issue, employees
    ) -> None:
        """Администратору принадлежность безразлична — ядро дёргать незачем."""
        await client.get("/templates", headers=auth(issue()))
        assert employees.lookups == []

    async def test_forged_employee_is_overwritten(self, client, issue, upstream) -> None:
        headers = auth(issue(realm_access={"roles": ["specialist"]})) | {
            HEADER_EMPLOYEE: "00000000-dead-4000-8000-000000000000",
        }
        await client.get("/templates", headers=headers)
        assert upstream.last.headers[HEADER_EMPLOYEE] == EMPLOYEE_ID

    async def test_trace_continues(self, client, issue, upstream) -> None:
        traceparent = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
        headers = auth(issue()) | {"traceparent": traceparent}
        response = await client.get("/templates", headers=headers)
        assert upstream.last.headers["traceparent"] == traceparent
        assert response.headers["traceparent"] == traceparent

    async def test_status_from_upstream_passes_through(self, settings, verifier, issue) -> None:
        from app.infra.lifespan import AppContext
        from app.main import create_app
        from app.routing.matcher import Router

        def refuse(_: httpx.Request) -> httpx.Response:
            return httpx.Response(409, json={"detail": "слот занят"})

        proxy = Proxy(
            settings.upstreams(),
            client=httpx.AsyncClient(transport=httpx.MockTransport(refuse)),
        )
        app = create_app(
            AppContext(settings, None, verifier, Router(), proxy, StubEmployees())
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as instance:
            response = await instance.post("/appointments", headers=auth(issue()), json={})
        assert response.status_code == 409
        assert response.json() == {"detail": "слот занят"}


class TestUpstreamFailure:
    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            (httpx.ConnectError("отказано в соединении"), 503),
            (httpx.ReadTimeout("сосед молчит"), 504),
        ],
    )
    async def test_broken_upstream_is_not_our_five_hundred(
        self, settings, verifier, issue, error, expected
    ) -> None:
        from app.infra.lifespan import AppContext
        from app.main import create_app
        from app.routing.matcher import Router

        def fail(_: httpx.Request) -> httpx.Response:
            raise error

        proxy = Proxy(
            settings.upstreams(),
            client=httpx.AsyncClient(transport=httpx.MockTransport(fail)),
        )
        app = create_app(
            AppContext(settings, None, verifier, Router(), proxy, StubEmployees())
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://gateway") as instance:
            response = await instance.get("/templates", headers=auth(issue()))
        assert response.status_code == expected
