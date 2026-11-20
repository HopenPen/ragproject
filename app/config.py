# Назначение файла: единые настройки процессов, секреты из env/files и limits.
from functools import lru_cache
from pathlib import Path
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    app_mode: str = 'backend'
    environment: str = 'development'
    database_url: str = 'postgresql+psycopg://science@postgres/science'
    rabbitmq_url: SecretStr = SecretStr('amqp://science@rabbitmq:5672/science')
    redis_url: str = 'redis://redis:6379/0'
    s3_endpoint: str = 'http://minio:9000'
    s3_bucket: str = 'science-extract'
    s3_access_key: SecretStr = SecretStr('')
    s3_secret_key: SecretStr = SecretStr('')
    jwt_issuer: str = 'science-extract'
    jwt_audience: str = 'science-extract-api'
    jwt_key_path: Path = Path('/keys/private.pem')
    jwt_public_path: Path = Path('/public-keys/jwks.json')
    gateway_secret: SecretStr = SecretStr('')
    admin_email: str = ''
    admin_password: SecretStr = SecretStr('')
    openai_api_key: SecretStr = SecretStr('')
    model_id: str = 'gpt-6.1-terra'
    max_pdf_bytes: int = Field(100 * 1024 * 1024, gt=0)
    max_pdf_pages: int = Field(300, gt=0)
    model_timeout: float = 180
    max_retries: int = Field(3, ge=0, le=3)
    model_max_calls: int = Field(250, ge=1)
    model_max_output_tokens: int = 24000
    page_batch_size: int = Field(3, ge=1, le=10)
    render_dpi: int = Field(120, ge=72, le=200)
    allowed_origins: list[str] = []
    log_level: str = 'INFO'
    public_base_url: str = 'http://localhost'
    dispatcher_enabled: bool = True
    lease_seconds: int = 600
    export_retention_days: int = 7
    external_checker_path: Path | None = None
    runtime_path: Path = Path('/runtime')

    @model_validator(mode='before')
    @classmethod
    def secret_files(cls, values):
        import os
        for name in ('database_url', 'rabbitmq_url', 's3_access_key', 's3_secret_key',
                     'gateway_secret', 'admin_password', 'openai_api_key'):
            path = os.environ.get(name.upper() + '_FILE')
            if path:
                values[name] = Path(path).read_text(encoding='utf-8').strip()
        return values


@lru_cache
def settings():
    return Settings()
