from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "prod"

    db_solscore_host: str
    db_solscore_port: int = 5432
    db_solscore_name: str
    db_solscore_user: str
    db_solscore_password: SecretStr

    oidc_issuer: str
    oidc_audience: str

    auth_dev_token: SecretStr | None = None
    auth_dev_user: str = "dev@fondasol.fr"

    cors_origins: str = ""

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


config = Config()
