from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    """Service settings. Environment variables take precedence over the .env file.

    Defaults match the in-container values used by docker-compose.yml and the orchestrator
    (host `auth-db`, port 5432). To run the app or Alembic from the host, copy .env.example to .env.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    service_name: str = "auth-user-service"
    database_host: str = "auth-db"
    database_port: int = 5432
    database_name: str = "auth_db"
    database_user: str = "postgres"
    database_password: str = "postgres"

    auth0_domain: str = ""
    auth0_client_id: str = ""
    auth0_db_connection: str = "Username-Password-Authentication"
    auth0_timeout_seconds: float = 5.0

    password_reset_max_requests: int = 3
    password_reset_window_seconds: int = 900

    @property
    def database_url(self) -> str:
        """Async DSN. URL.create escapes special characters in the credentials (e.g. '@' or '/')."""
        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.database_user,
            password=self.database_password,
            host=self.database_host,
            port=self.database_port,
            database=self.database_name,
        ).render_as_string(hide_password=False)


settings = Settings()
