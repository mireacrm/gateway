import httpx

from app.security.employees import EmployeeDirectory

SUBJECT = "8f1c0e4e-0000-4000-8000-000000000001"
EMPLOYEE = "3a7c9d21-0000-4000-8000-0000000000aa"


class FakeCore:
    def __init__(self, status: int = 200, employee_id: str = EMPLOYEE) -> None:
        self.calls = 0
        self._status = status
        self._employee_id = employee_id

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self._status != 200:
            return httpx.Response(self._status, json={"detail": "нет"})
        return httpx.Response(200, json={
            "employee_id": self._employee_id,
            "branch_id": "b1",
            "role": "specialist",
        })

    def directory(
        self, ttl: float = 60.0, missing_ttl: float = 5.0, capacity: int = 4096
    ) -> EmployeeDirectory:
        client = httpx.AsyncClient(transport=httpx.MockTransport(self.handler))
        return EmployeeDirectory("http://core:8001", ttl, client, missing_ttl, capacity)


class TestResolution:
    async def test_returns_employee(self) -> None:
        assert await FakeCore().directory().employee_id(SUBJECT) == EMPLOYEE

    async def test_unknown_account_is_not_an_error(self) -> None:
        """Учётная запись без сотрудника — обычное дело, а не сбой."""
        assert await FakeCore(status=404).directory().employee_id(SUBJECT) == ""


class TestCache:
    async def test_second_call_does_not_reach_core(self) -> None:
        core = FakeCore()
        directory = core.directory()
        for _ in range(5):
            await directory.employee_id(SUBJECT)
        assert core.calls == 1

    async def test_absence_is_cached_too(self) -> None:
        """Иначе учётная запись без сотрудника бьёт по ядру на каждом запросе."""
        core = FakeCore(status=404)
        directory = core.directory()
        for _ in range(5):
            await directory.employee_id(SUBJECT)
        assert core.calls == 1

    async def test_expired_entry_is_refreshed(self) -> None:
        core = FakeCore()
        directory = core.directory(ttl=0.0)
        await directory.employee_id(SUBJECT)
        await directory.employee_id(SUBJECT)
        assert core.calls == 2

    async def test_forget_drops_entry(self) -> None:
        core = FakeCore()
        directory = core.directory()
        await directory.employee_id(SUBJECT)
        directory.forget(SUBJECT)
        await directory.employee_id(SUBJECT)
        assert core.calls == 2


class TestCoreUnavailable:
    async def test_failure_is_not_cached(self) -> None:
        """Недоступность ядра временна: закэшировать её значит продлить сбой."""
        def fail(_: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("отказано в соединении")

        client = httpx.AsyncClient(transport=httpx.MockTransport(fail))
        directory = EmployeeDirectory("http://core:8001", 60.0, client)
        assert await directory.employee_id(SUBJECT) == ""
        assert await directory.employee_id(SUBJECT) == ""

    async def test_unexpected_status_denies_access(self) -> None:
        assert await FakeCore(status=500).directory().employee_id(SUBJECT) == ""


class TestMissingAccount:
    async def test_absence_expires_sooner_than_match(self) -> None:
        """Сотрудника только что привязали к учётной записи.

        Пока отсутствие лежит в кэше, специалист получает 403 на свои же
        визиты, и выглядит это как проблема с правами, а не как кэш.
        Поэтому отрицательный ответ живёт заметно меньше положительного.
        """
        core = FakeCore(status=404)
        directory = core.directory(ttl=60.0, missing_ttl=0.0)
        assert await directory.employee_id(SUBJECT) == ""
        assert await directory.employee_id(SUBJECT) == ""
        assert core.calls == 2

    async def test_match_still_cached(self) -> None:
        core = FakeCore()
        directory = core.directory(ttl=60.0, missing_ttl=0.0)
        assert await directory.employee_id(SUBJECT) == EMPLOYEE
        assert await directory.employee_id(SUBJECT) == EMPLOYEE
        assert core.calls == 1


class TestCapacity:
    async def test_cache_does_not_grow_without_bound(self) -> None:
        """Кэш живёт столько же, сколько процесс, и растёт по числу
        когда-либо заходивших. Без вытеснения это утечка."""
        core = FakeCore()
        directory = core.directory(capacity=8)
        for number in range(50):
            await directory.employee_id(f"subject-{number}")
        assert len(directory._cache) <= 8
