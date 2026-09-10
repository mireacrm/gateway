import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from app.infra.config import Settings
from app.routing.matcher import Router
from app.routing.proxy import Proxy
from app.security.employees import EmployeeDirectory
from app.security.keycloak import Keycloak
from app.security.tokens import TokenVerifier

log = logging.getLogger(__name__)


@dataclass(slots=True)
class AppContext:
    settings: Settings
    keycloak: Keycloak
    verifier: TokenVerifier
    router: Router
    proxy: Proxy
    employees: EmployeeDirectory


@asynccontextmanager
async def build_context(settings: Settings) -> AsyncIterator[AppContext]:
    keycloak = Keycloak(settings)
    proxy = Proxy(settings.upstreams(), settings.upstream_timeout)
    employees = EmployeeDirectory(settings.core_url, settings.employee_cache_ttl)

    # Ключи тянем сразу, но неудача не мешает старту: Keycloak может подняться
    # позже, а до первого запроса с токеном они и не нужны.
    if not await keycloak.keys.refresh(force=True):
        log.warning("ключи Keycloak недоступны на старте, попробуем при первом запросе")

    try:
        yield AppContext(
            settings=settings,
            keycloak=keycloak,
            verifier=TokenVerifier(settings, keycloak.keys),
            router=Router(),
            proxy=proxy,
            employees=employees,
        )
    finally:
        await proxy.close()
        await employees.close()
        await keycloak.close()
