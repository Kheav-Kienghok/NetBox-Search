from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App configuration, populated from environment variables or a .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # NetBox connection
    netbox_url: str = "https://netbox.example.com"
    netbox_token: str = ""
    netbox_verify_ssl: bool = True
    netbox_timeout: float = 30.0

    # Sync behaviour
    sync_interval_hours: float = 4.0
    sync_on_startup: bool = True

    # Storage
    db_path: str = "data/netbox_search.db"

    # Web server
    host: str = "0.0.0.0"
    port: int = 8000


settings = Settings()
