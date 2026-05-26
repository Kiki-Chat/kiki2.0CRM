from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_jwt_secret: str = ""

    master_webhook_secret: str = "change-me"
    post_call_webhook_secret: str = ""

    cors_origins: str = "http://localhost:5173"

    elevenlabs_api_key: str = ""

    # Symmetric key (Fernet) for encrypting stored third-party credentials.
    settings_enc_key: str = ""

    # OAuth (P1.8) — credentials per provider. Placeholders until set per
    # P1.8_OAUTH_SETUP.md. When any *_client_id is empty, the corresponding
    # /api/settings/oauth/{provider}/authorize returns 503.
    google_client_id: str = ""
    google_client_secret: str = ""
    ms_client_id: str = ""
    ms_client_secret: str = ""
    # Used to build OAuth redirect URIs at runtime. Must match the value
    # registered with Google + Azure (see §1.4 / §2.1 of P1.8_OAUTH_SETUP.md).
    backend_public_url: str = "http://localhost:8000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
