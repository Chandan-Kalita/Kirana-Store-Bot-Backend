from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    telegram_bot_token: str
    webhook_secret: str
    anthropic_api_key: str
    anthropic_base_url: str | None = None
    # points at DeepSeek's Anthropic-compatible endpoint, not api.anthropic.com
    anthropic_model: str = "deepseek-chat"

    # invoice header -- swap get_shop_header()'s internals to a Preference
    # lookup once Phase 7 lands, callers don't change
    shop_name: str = "Kirana Store"
    shop_gstin: str | None = 1111222233334444

    # Cloud Run/Cloud Tasks wiring -- set by terraform/cloud_run.tf on the
    # deployed service. task_handler_path defaults to match the Terraform
    # variable's default (terraform/variables.tf) for local dev.
    gcp_project: str
    cloud_tasks_queue: str
    cloud_tasks_location: str
    tasks_invoker_service_account: str
    task_handler_path: str = "/tasks/handle"
    # The service's own https URL -- used to build Cloud Tasks targets/OIDC
    # audiences. Not derived from the incoming request: Cloud Run terminates
    # TLS ahead of the container, and trusting X-Forwarded-Proto from its
    # proxy is exactly the kind of thing that's easy to get wrong.
    service_url: str = ""

    @property
    def task_handler_url(self) -> str:
        return self.service_url.rstrip("/") + self.task_handler_path

    port: int = 8080


@lru_cache
def get_settings() -> Settings:
    return Settings()
