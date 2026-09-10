from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GATEWAY_", env_file=".env", extra="ignore")

    service_name: str = "gateway"
    http_port: int = 8000
    debug: bool = False
    # Пустой адрес выключает экспорт трасс: нужен для тестов
    # и запуска без инфраструктуры.
    otlp_endpoint: str = ""

    # Keycloak подставляет в iss тот адрес, по которому к нему пришёл браузер,
    # а ключи шлюз забирает изнутри сети. Адреса разные, и оба нужны.
    oidc_issuer: str = "http://localhost:8080/realms/mirea"
    oidc_internal_url: str = ""
    oidc_audience: str = "mirea-api"
    oidc_client_id: str = "mirea-web"
    oidc_algorithms: tuple[str, ...] = ("RS256",)
    jwks_cooldown: float = 30.0
    clock_skew: int = 10

    # Связь учётной записи с сотрудником меняется редко, а спрашивается
    # на каждом запросе непривилегированного вызывающего.
    employee_cache_ttl: float = 60.0
    upstream_timeout: float = 10.0
    core_url: str = "http://localhost:8001"
    catalog_url: str = "http://localhost:8002"
    booking_url: str = "http://localhost:8003"
    inventory_url: str = "http://localhost:8004"
    client_url: str = "http://localhost:8005"
    billing_url: str = "http://localhost:8006"
    notification_url: str = "http://localhost:8007"
    analytics_url: str = "http://localhost:8008"

    @property
    def oidc_base(self) -> str:
        return (self.oidc_internal_url or self.oidc_issuer).rstrip("/")

    @property
    def jwks_url(self) -> str:
        return f"{self.oidc_base}/protocol/openid-connect/certs"

    @property
    def token_url(self) -> str:
        return f"{self.oidc_base}/protocol/openid-connect/token"

    def upstreams(self) -> dict[str, str]:
        return {
            "core": self.core_url,
            "catalog": self.catalog_url,
            "booking": self.booking_url,
            "inventory": self.inventory_url,
            "client": self.client_url,
            "billing": self.billing_url,
            "notification": self.notification_url,
            "analytics": self.analytics_url,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
