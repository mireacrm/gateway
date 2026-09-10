"""Публичные ключи Keycloak.

Ключи меняются при ротации, поэтому кэш обновляется по незнакомому kid.
Обновление ограничено по частоте: иначе поток запросов с выдуманным kid
превращается в поток запросов к Keycloak.

Ограничение считается по попытке, а не по удаче. Иначе оно отключается ровно
тогда, когда нужнее всего: недоступный Keycloak не обновляет отметку времени,
и каждый запрос по очереди ждёт свой таймаут под общим локом. После неудачи
пауза короче — Keycloak может подняться через секунду, и держать отказ
полминуты незачем.
"""

import asyncio
import json
import logging
from time import monotonic

import httpx
from jwt.algorithms import RSAAlgorithm

log = logging.getLogger(__name__)


class KeyStore:
    def __init__(
        self,
        url: str,
        cooldown: float = 30.0,
        client: httpx.AsyncClient | None = None,
        retry_cooldown: float = 2.0,
    ):
        self._url = url
        self._cooldown = cooldown
        self._retry_cooldown = retry_cooldown
        self._client = client or httpx.AsyncClient(timeout=5.0)
        self._owns_client = client is None
        self._keys: dict[str, object] = {}
        self._attempted_at = float("-inf")
        self._failed = False
        self._lock = asyncio.Lock()

    @property
    def loaded(self) -> bool:
        return bool(self._keys)

    async def key(self, kid: str) -> object | None:
        key = self._keys.get(kid)
        if key is not None:
            return key
        await self.refresh()
        return self._keys.get(kid)

    async def refresh(self, force: bool = False) -> bool:
        async with self._lock:
            cooldown = self._retry_cooldown if self._failed else self._cooldown
            if not force and monotonic() - self._attempted_at < cooldown:
                return bool(self._keys)

            # Отметка ставится по завершении попытки, а не в её начале:
            # неудачная попытка длится до таймаута, и отсчёт от её старта
            # означал бы, что пауза истекла ещё до того, как мы про неудачу
            # узнали. Соседние запросы всё это время ждут на локе.
            try:
                response = await self._client.get(self._url)
                response.raise_for_status()
                document = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                self._failed = True
                log.warning("не удалось получить JWKS: %s", exc)
                return False
            finally:
                self._attempted_at = monotonic()

            self._failed = False
            self._keys = {
                jwk["kid"]: RSAAlgorithm.from_jwk(json.dumps(jwk))
                for jwk in document.get("keys", ())
                if jwk.get("kty") == "RSA" and jwk.get("use", "sig") == "sig"
            }
            log.info("ключи Keycloak обновлены: %s", ", ".join(self._keys) or "пусто")
            return bool(self._keys)

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
