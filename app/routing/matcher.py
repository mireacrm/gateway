"""Разбор пути по маршрутной таблице."""

from app.infra.errors import MethodNotAllowedError, UnknownRouteError
from app.routing.table import ROUTES, Route


class Router:
    def __init__(self, routes: tuple[Route, ...] = ROUTES) -> None:
        self._routes = routes

    def resolve(self, method: str, path: str) -> Route:
        segments = tuple(segment for segment in path.split("/") if segment)
        matched = [item for item in self._routes if _matches(item.pattern, segments)]
        if not matched:
            raise UnknownRouteError(method, path)

        allowed = [item for item in matched if item.method == method.upper()]
        if not allowed:
            raise MethodNotAllowedError(sorted({item.method for item in matched}))

        # Литеральный сегмент всегда точнее звёздочки: /clients/search должен
        # выиграть у /clients/*, в каком бы порядке они ни стояли в таблице.
        return max(allowed, key=lambda item: item.specificity)

    def routes(self) -> tuple[Route, ...]:
        return self._routes


def _matches(pattern: tuple[str, ...], segments: tuple[str, ...]) -> bool:
    if len(pattern) != len(segments):
        return False
    pairs = zip(pattern, segments, strict=True)
    return all(expected in ("*", actual) for expected, actual in pairs)
