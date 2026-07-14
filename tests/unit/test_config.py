from app.core.config import Settings


def test_async_uri_is_built_from_parts() -> None:
    s = Settings(
        POSTGRES_USER="u",
        POSTGRES_PASSWORD="p",
        POSTGRES_HOST="db",
        POSTGRES_PORT=5432,
        POSTGRES_DB="d",
        DATABASE_URL=None,
    )
    assert s.async_database_uri == "postgresql+asyncpg://u:p@db:5432/d"
    assert s.sync_database_uri == "postgresql://u:p@db:5432/d"


def test_cors_origins_accepts_comma_separated_string() -> None:
    s = Settings(CORS_ORIGINS="http://a.com, http://b.com")
    assert s.CORS_ORIGINS == ["http://a.com", "http://b.com"]


def test_is_production_flag() -> None:
    assert Settings(ENVIRONMENT="production").is_production
    assert not Settings(ENVIRONMENT="local").is_production
