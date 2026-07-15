from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    telegram_bot_token: str
    webhook_secret: str
    anthropic_api_key: str
    anthropic_base_url: str | None = None

    # Cloud Run/Cloud Tasks wiring -- set by terraform/cloud_run.tf on the
    # deployed service. task_handler_path defaults to match the Terraform
    # variable's default (terraform/variables.tf) for local dev.
    gcp_project: str
    cloud_tasks_queue: str
    cloud_tasks_location: str
    tasks_invoker_service_account: str
    task_handler_path: str = "/tasks/handle"

    port: int = 8080


@lru_cache
def get_settings() -> Settings:
    return Settings()
