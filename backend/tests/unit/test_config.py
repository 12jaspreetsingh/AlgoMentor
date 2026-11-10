from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.models import User
from app.models.base import UTCDateTime


def test_settings_default_timezone_and_secret_redaction(settings):
    assert settings.default_timezone == "Asia/Kolkata"
    assert "test:test" not in repr(settings)


@pytest.mark.parametrize("url", ["sqlite:///app.db", "postgresql://host/db", "not-a-url"])
def test_only_explicit_postgres_driver_is_allowed(url):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=url)


def test_missing_url_fails_early(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError, match="database_url"):
        Settings(_env_file=None)


def test_invalid_timezone_rejected(settings):
    with pytest.raises(ValidationError, match="valid IANA timezone"):
        Settings(
            _env_file=None, database_url=settings.database_url, default_timezone="Mars/Olympus"
        )
    with pytest.raises(ValueError, match="valid IANA timezone"):
        User(timezone="Mars/Olympus")


def test_invalid_configuration_error_does_not_print_secret():
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, database_url="mysql://owner:private-password@host/db")
    assert "private-password" not in str(error.value)


def test_timestamps_require_offset_and_convert_to_utc():
    column_type = UTCDateTime()
    with pytest.raises(ValueError, match="timezone offset"):
        column_type.process_bind_param(datetime(2026, 11, 10, 0, 15), None)
    instant = datetime(2026, 11, 10, 0, 15, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    assert column_type.process_bind_param(instant, None) == datetime(
        2026, 11, 9, 18, 45, tzinfo=timezone.utc
    )
    assert column_type.process_bind_param(None, None) is None
