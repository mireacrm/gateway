"""Проксирование запроса во внутренний сервис."""

import logging

import httpx
from fastapi import Request, Response
from mireacrm_common import tracing

from app.infra.errors import UpstreamTimeoutError, UpstreamUnavailableError
from app.security.principal import HEADERS, Principal

log = logging.getLogger(__name__)

# Заголовки соединения принадлежат конкретному хопу и дальше не едут.
_HOP_BY_HOP = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade",
})
# Authorization дальше не идёт: за периметром токен уже проверен, а его утечка
# в логи восьми сервисов ничего не даёт. Заголовки личности выставляет шлюз, и
# пришедшие снаружи одноимённые заголовки затираются — иначе личность подделает
# любой, кто знает их названия.
_DROP_REQUEST = _HOP_BY_HOP | HEADERS | {"host", "content-length", "authorization"}
_DROP_RESPONSE = _HOP_BY_HOP | {"content-length", "content-encoding"}


class Proxy:
    def __init__(
        self,
        upstreams: dict[str, str],
        timeout: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._upstreams = {name: url.rstrip("/") for name, url in upstreams.items()}
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=2.0))

    async def forward(self, upstream: str, request: Request, principal: Principal) -> Response:
        base = self._upstreams[upstream]
        headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower() not in _DROP_REQUEST
        }
        headers.update(principal.headers())
        headers[tracing.HEADER] = tracing.current()

        outgoing = self._client.build_request(
            request.method,
            f"{base}{request.url.path}",
            params=request.query_params,
            headers=headers,
            content=await request.body(),
        )
        try:
            response = await self._client.send(outgoing)
        except httpx.TimeoutException as exc:
            log.warning("%s не ответил вовремя: %s", upstream, exc)
            raise UpstreamTimeoutError(upstream) from exc
        except httpx.HTTPError as exc:
            log.warning("%s недоступен: %s", upstream, exc)
            raise UpstreamUnavailableError(upstream) from exc

        return Response(
            content=response.content,
            status_code=response.status_code,
            headers={
                key: value
                for key, value in response.headers.items()
                if key.lower() not in _DROP_RESPONSE
            },
        )

    async def close(self) -> None:
        await self._client.aclose()
