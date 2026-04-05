from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # Database
    database_url: str
    test_database_url: str | None = None  # Only needed when running tests

    # Authentication
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # Anthropic
    anthropic_api_key: str

    # Application
    debug: bool = False


settings = Settings()  # type: ignore[call-arg]

"""
Import this anywhere: 

```
from notesmith.config import settings

print(settings.database_url)
```
"""
