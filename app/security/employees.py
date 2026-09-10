"""Соответствие учётной записи и сотрудника.

Проверять принадлежность объекта обязан сервис-владелец, но сопоставить
учётную запись с сотрудником он не может: справочник сотрудников ведёт
core-service. Шлюз выясняет это один раз и передаёт результат в заголовке —
иначе к ядру ходил бы каждый сервис на каждом запросе.

Спрашивается только для непривилегированных вызывающих: администратору и
управляющему принадлежность не важна, и обращаться к ядру незачем.
"""

import logging
from time import monotonic

import httpx

log = logging.getLogger(__name__)


class EmployeeDirectory:
    def __init__(
        self,
        core_url: str,
        ttl: float = 60.0,
        client: httpx.AsyncClient | None = None,
        missing_ttl: float = 5.0,
        capacity: int = 4096,
    ):
        self._url = core_url.rstrip("/")
        self._ttl = ttl
        # Отсутствие соответствия живёт в кэше заметно меньше найденного.
        # Администратор только что привязал специалиста к учётной записи —
        # и до истечения срока тот получал бы 403 на собственные визиты,
        # причём выглядело бы это как проблема с правами, а не как кэш.
        # Обратный случай безобиден: сотрудника не отвязывают ежеминутно.
        self._missing_ttl = missing_ttl
        self._capacity = capacity
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=2.0))
        self._owns_client = client is None
        self._cache: dict[str, tuple[float, str]] = {}

    async def employee_id(self, subject: str) -> str:
        """Сотрудник, соответствующий учётной записи, или пустая строка.

        Отсутствие соответствия — обычное дело: учётная запись может не
        принадлежать сотруднику. Пустой ответ приводит к отказу в доступе
        на стороне сервиса, а не к ошибке здесь.
        """
        cached = self._cache.get(subject)
        if cached is not None and monotonic() - cached[0] < self._lifetime(cached[1]):
            return cached[1]

        try:
            response = await self._client.get(
                f"{self._url}/internal/employees/by-subject/{subject}"
            )
        except httpx.HTTPError as exc:
            # Ядро недоступно: кэшировать нечего, пробуем на следующем запросе.
            log.warning("не удалось сопоставить учётную запись: %s", exc)
            return ""

        if response.status_code == httpx.codes.NOT_FOUND:
            employee_id = ""
        elif response.status_code == httpx.codes.OK:
            employee_id = response.json().get("employee_id", "")
        else:
            log.warning("ядро ответило %s при сопоставлении", response.status_code)
            return ""

        self._remember(subject, employee_id)
        return employee_id

    def _lifetime(self, employee_id: str) -> float:
        return self._ttl if employee_id else self._missing_ttl

    def _remember(self, subject: str, employee_id: str) -> None:
        if len(self._cache) >= self._capacity and subject not in self._cache:
            self._evict()
        self._cache[subject] = (monotonic(), employee_id)

    def _evict(self) -> None:
        """Кэш растёт по числу когда-либо заходивших, а живёт столько же,
        сколько процесс. Сначала выбрасываем протухшее; если и после этого
        места нет, то самое старое."""
        now = monotonic()
        self._cache = {
            subject: entry
            for subject, entry in self._cache.items()
            if now - entry[0] < self._lifetime(entry[1])
        }
        while len(self._cache) >= self._capacity:
            oldest = min(self._cache, key=lambda subject: self._cache[subject][0])
            del self._cache[oldest]

    def forget(self, subject: str) -> None:
        """Забыть соответствие, не дожидаясь срока: сотрудника переназначили."""
        self._cache.pop(subject, None)

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
