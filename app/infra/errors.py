class GatewayError(Exception):
    """База ошибок шлюза. Каждая имеет ровно один код HTTP."""


class UnauthenticatedError(GatewayError):
    """Кто вызывает — неизвестно: токена нет или он не проходит проверку."""


class ForbiddenError(GatewayError):
    def __init__(self, required: frozenset[str], actual: frozenset[str]) -> None:
        super().__init__(
            f"требуется роль {' или '.join(sorted(required))}; "
            f"выдано: {', '.join(sorted(actual)) or 'ни одной'}"
        )
        self.required = required
        self.actual = actual


class UnknownRouteError(GatewayError):
    def __init__(self, method: str, path: str) -> None:
        super().__init__(f"{method} {path} не объявлен в маршрутной таблице")


class MethodNotAllowedError(GatewayError):
    def __init__(self, allowed: list[str]) -> None:
        super().__init__(f"метод не поддерживается; разрешены: {', '.join(allowed)}")
        self.allowed = allowed


class UpstreamUnavailableError(GatewayError):
    def __init__(self, upstream: str) -> None:
        super().__init__(f"{upstream} недоступен")
        self.upstream = upstream


class UpstreamTimeoutError(GatewayError):
    def __init__(self, upstream: str) -> None:
        super().__init__(f"{upstream} не ответил вовремя")
        self.upstream = upstream
