from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: str = "development"
    database_host: str = "db"
    database_name: str = "discordia_auth"
    database_port: int = 5432
    database_user: str = "admin"
    database_password: str = "password"

    @property
    def database_url(self) -> str:
        return f"postgresql+asyncpg://{self.database_user}:{self.database_password}@{self.database_host}:{self.database_port}/{self.database_name}"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()