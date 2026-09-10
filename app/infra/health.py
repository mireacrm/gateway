"""Проверки живости и готовности.

Готовность шлюза — это доступность Keycloak: без ключей он не пропустит
ни одного запроса. Состояние сервисов за ним намеренно не проверяется:
упавший склад не повод переставать пускать запросы к записям.
"""

from dataclasses import dataclass

from app.infra.lifespan import AppContext


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    checks: dict[str, str]

    @property
    def ready(self) -> bool:
        return all(status == "ok" for status in self.checks.values())


async def check_readiness(context: AppContext) -> ReadinessReport:
    keys = context.keycloak.keys
    available = keys.loaded or await keys.refresh()
    return ReadinessReport({"keycloak": "ok" if available else "unreachable"})
