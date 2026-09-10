import httpx

from app.security.jwks import KeyStore

JWKS = {
    "keys": [
        {
            "kid": "live",
            "kty": "RSA",
            "use": "sig",
            "alg": "RS256",
            "n": "sXchDaQebHnPiGvyDOAT4saGEUetSyo9MKLOoWFsueri23bOdgWp4Dy1Wl"
                 "UzewbgBHod5pcM9H95GQRV3JDXboIRROSBigeC5yjU1hGzHHyXss8UDpre"
                 "cbAYxknTcQkhslANGRUZmdTOQ5qTRsLAt6BTYuyvVRdhS8exSZEy_c4gs_"
                 "7svlJJQ4H9_NxsiIoLwAEk7-Q3UXERGYw_75IDrGA84-lA_-Ct4eTlXHBI"
                 "Y2EaV7t7LjJaynVJCpkv4LKjTTAumiGUIuQhrNhZLuF_RJLqHpM2kgWFLU"
                 "7-VTdL1VbC2tejvcI2BlMkEpk1BzBZI0KQB0GaDWFLN-aEAw3vRw",
            "e": "AQAB",
        },
        {"kid": "encryption", "kty": "RSA", "use": "enc", "n": "abc", "e": "AQAB"},
        {"kid": "elliptic", "kty": "EC", "crv": "P-256", "x": "abc", "y": "def"},
    ]
}


class CountingKeycloak:
    def __init__(self, status: int = 200) -> None:
        self.calls = 0
        self._status = status

    def handler(self, _: httpx.Request) -> httpx.Response:
        self.calls += 1
        return httpx.Response(self._status, json=JWKS if self._status == 200 else {})

    def store(self, cooldown: float = 30.0, retry_cooldown: float = 2.0) -> KeyStore:
        transport = httpx.MockTransport(self.handler)
        return KeyStore(
            "http://keycloak/certs",
            cooldown,
            httpx.AsyncClient(transport=transport),
            retry_cooldown,
        )


class TestKeyStore:
    async def test_loads_only_signing_rsa_keys(self) -> None:
        """Ключи шифрования и кривые под RS256 не годятся."""
        store = CountingKeycloak().store()
        assert await store.refresh() is True
        assert await store.key("live") is not None
        assert await store.key("encryption") is None
        assert await store.key("elliptic") is None

    async def test_known_key_served_from_cache(self) -> None:
        keycloak = CountingKeycloak()
        store = keycloak.store()
        await store.refresh()
        for _ in range(5):
            await store.key("live")
        assert keycloak.calls == 1

    async def test_unknown_kid_does_not_hammer_keycloak(self) -> None:
        """Поток токенов с выдуманным kid не должен превращаться в поток запросов."""
        keycloak = CountingKeycloak()
        store = keycloak.store(cooldown=60.0)
        await store.refresh()
        for _ in range(20):
            assert await store.key("forged") is None
        assert keycloak.calls == 1

    async def test_rotation_picked_up_after_cooldown(self) -> None:
        keycloak = CountingKeycloak()
        store = keycloak.store(cooldown=0.0)
        await store.refresh()
        await store.key("forged")
        assert keycloak.calls == 2

    async def test_unreachable_keycloak_reported_not_raised(self) -> None:
        """Шлюз должен ответить 503, а не упасть с трассой стека."""
        store = CountingKeycloak(status=500).store()
        assert await store.refresh() is False
        assert store.loaded is False

    async def test_unreachable_keycloak_is_not_hammered(self) -> None:
        """Пауза считается по попытке, а не по удаче.

        Иначе ограничение частоты отключается ровно тогда, когда нужнее
        всего: неудача не двигает отметку времени, и каждый запрос идёт
        в недоступный Keycloak ждать свой таймаут.
        """
        keycloak = CountingKeycloak(status=500)
        store = keycloak.store(retry_cooldown=60.0)
        for _ in range(20):
            assert await store.key("live") is None
        assert keycloak.calls == 1

    async def test_recovery_not_delayed_by_full_cooldown(self) -> None:
        """После неудачи ждём коротко: Keycloak мог подняться через секунду,
        а держать отказ полминуты означало бы отвергать годные токены."""
        keycloak = CountingKeycloak(status=500)
        store = keycloak.store(cooldown=60.0, retry_cooldown=0.0)
        assert await store.key("live") is None
        assert await store.key("live") is None
        assert keycloak.calls == 2
