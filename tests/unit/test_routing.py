import pytest

from app.infra.errors import MethodNotAllowedError, UnknownRouteError
from app.routing.matcher import Router
from app.routing.table import ROUTES, route


class TestResolve:
    def setup_method(self) -> None:
        self.router = Router()

    def test_picks_service_by_tail_of_path(self) -> None:
        """Один и тот же префикс ведёт в разные сервисы — решает хвост."""
        assert self.router.resolve("GET", "/branches/b1/employees").upstream == "core"
        assert self.router.resolve("GET", "/branches/b1/services").upstream == "catalog"
        assert self.router.resolve("GET", "/branches/b1/slots").upstream == "booking"
        assert self.router.resolve("GET", "/branches/b1/stock").upstream == "inventory"
        assert self.router.resolve("GET", "/branches/b1/invoices").upstream == "billing"
        assert self.router.resolve("GET", "/branches/b1/revenue").upstream == "analytics"

    def test_literal_beats_wildcard(self) -> None:
        routes = (
            route("GET", "/clients/*", "client", frozenset({"admin"}), "карточка"),
            route("GET", "/clients/active", "client", frozenset({"admin"}), "список"),
        )
        assert Router(routes).resolve("GET", "/clients/active").summary == "список"

    def test_trailing_slash_ignored(self) -> None:
        assert self.router.resolve("GET", "/templates/").upstream == "notification"

    def test_unknown_path_rejected(self) -> None:
        with pytest.raises(UnknownRouteError):
            self.router.resolve("GET", "/branches/b1/unknown")

    def test_wrong_method_reports_allowed(self) -> None:
        with pytest.raises(MethodNotAllowedError) as raised:
            self.router.resolve("DELETE", "/companies")
        assert raised.value.allowed == ["POST"]


class TestTable:
    def test_every_route_points_to_known_upstream(self, settings) -> None:
        upstreams = set(settings.upstreams())
        assert {item.upstream for item in ROUTES} <= upstreams

    def test_no_route_is_open_to_everyone(self) -> None:
        """Пустой набор ролей означал бы маршрут без проверки прав."""
        assert all(item.roles for item in ROUTES)

    def test_no_duplicates(self) -> None:
        keys = [(item.method, item.pattern) for item in ROUTES]
        assert len(keys) == len(set(keys))
