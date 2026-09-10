"""Маршрутная таблица: единственное место, где описаны права на запросы.

Шлюз проверяет роль, но не принадлежность объекта. Что специалист смотрит
именно своё расписание, а не чужое, решает сервис — ему для этого приходит
идентификатор пользователя в заголовках.
"""

from dataclasses import dataclass

ADMIN = frozenset({"admin"})
STAFF = frozenset({"admin", "manager"})
ANY = frozenset({"admin", "manager", "specialist"})


@dataclass(frozen=True, slots=True)
class Route:
    method: str
    pattern: tuple[str, ...]
    upstream: str
    roles: frozenset[str]
    summary: str

    @property
    def path(self) -> str:
        return "/" + "/".join(self.pattern)

    @property
    def specificity(self) -> int:
        return sum(1 for segment in self.pattern if segment != "*")


def route(method: str, path: str, upstream: str, roles: frozenset[str], summary: str) -> Route:
    return Route(
        method=method.upper(),
        pattern=tuple(segment for segment in path.split("/") if segment),
        upstream=upstream,
        roles=roles,
        summary=summary,
    )


ROUTES: tuple[Route, ...] = (
    route("POST", "/companies", "core", ADMIN, "Регистрация компании"),
    route("POST", "/companies/*/branches", "core", ADMIN, "Открытие филиала"),
    route("POST", "/branches/*/employees", "core", ADMIN, "Приём сотрудника"),
    route("GET", "/branches/*/employees", "core", STAFF, "Сотрудники филиала"),
    route("GET", "/employees/*/schedule", "core", ANY, "График сотрудника"),

    route("POST", "/services", "catalog", STAFF, "Добавление услуги"),
    route("GET", "/services/*", "catalog", ANY, "Карточка услуги"),
    route("GET", "/branches/*/services", "catalog", ANY, "Прайс филиала"),
    route("PUT", "/services/*/price", "catalog", ADMIN, "Изменение цены"),

    route("GET", "/branches/*/slots", "booking", ANY, "Свободные слоты"),
    route("POST", "/appointments", "booking", STAFF, "Создание записи"),
    route("GET", "/appointments/*", "booking", ANY, "Карточка записи"),
    route("POST", "/appointments/*/complete", "booking", ANY, "Закрытие визита"),
    route("POST", "/appointments/*/cancel", "booking", STAFF, "Отмена записи"),

    route("POST", "/clients", "client", STAFF, "Заведение клиента"),
    route("GET", "/clients", "client", STAFF, "Поиск клиента по телефону"),
    route("GET", "/clients/*", "client", STAFF, "Карточка клиента"),
    route("GET", "/clients/*/loyalty", "client", STAFF, "Лояльность клиента"),

    route("GET", "/branches/*/stock", "inventory", STAFF, "Остатки филиала"),
    route("GET", "/branches/*/stock/low", "inventory", STAFF, "Позиции ниже порога"),
    route("POST", "/branches/*/stock/replenish", "inventory", STAFF, "Пополнение склада"),
    route("PUT", "/branches/*/stock/*/threshold", "inventory", ADMIN, "Порог остатка"),

    route("GET", "/invoices/*", "billing", STAFF, "Счёт"),
    route("POST", "/invoices/*/pay", "billing", ADMIN, "Оплата счёта"),
    route("GET", "/branches/*/invoices", "billing", STAFF, "Счета филиала"),
    route("GET", "/employees/*/commission", "billing", ANY, "Комиссия сотрудника"),

    route("POST", "/notifications", "notification", STAFF, "Отправка уведомления"),
    route("GET", "/notifications/*", "notification", STAFF, "Статус уведомления"),
    route("GET", "/templates", "notification", ANY, "Шаблоны уведомлений"),

    route("GET", "/branches/*/revenue", "analytics", STAFF, "Выручка филиала"),
    route("GET", "/branches/*/funnel", "analytics", STAFF, "Воронка записей"),
    route("GET", "/employees/*/workload", "analytics", ANY, "Загрузка сотрудника"),
    route("GET", "/reports/consumables", "analytics", STAFF, "Расход материалов"),
)
