from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://cowork:cowork@localhost:5432/cowork"
    secret_key: str
    admin_username: str = "admin"
    admin_email: str = "admin@example.com"
    admin_password: str
    https_only: bool = False
    upload_dir: Path = Path("uploads")
    max_photo_mb: int = 5
    max_photos_per_space: int = 8
    bcrypt_rounds: int = 12
    timezone: str = "America/Bogota"
    demo_mode: bool = False  # muestra las cuentas de demostración en el login


settings = Settings()  # type: ignore[call-arg]  # los requeridos vienen del .env
