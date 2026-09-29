from urllib.parse import quote

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    """Service settings. Environment variables take precedence over the .env file.

    Defaults match the in-container values used by the orchestrator (host `auth-db`, port 5432;
    broker `rabbitmq`). To run the app, the outbox worker or Alembic from the host, copy
    .env.example to .env.
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

    cloudinary_cloud_name: str = ""
    cloudinary_api_key: str = ""
    cloudinary_api_secret: str = ""

    rabbitmq_host: str = "rabbitmq"
    rabbitmq_port: int = 5672
    rabbitmq_user: str = "admin"
    rabbitmq_password: str = "admin"
    rabbitmq_exchange: str = "user.events"

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

    @property
    def rabbitmq_url(self) -> str:
        """AMQP URL for the default vhost. Credentials are percent-encoded, like in database_url."""
        user = quote(self.rabbitmq_user, safe="")
        password = quote(self.rabbitmq_password, safe="")
        return f"amqp://{user}:{password}@{self.rabbitmq_host}:{self.rabbitmq_port}/"


settings = Settings()
