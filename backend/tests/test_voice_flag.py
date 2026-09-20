from app.config import Settings


def test_voice_on_in_development():
    s = Settings(app_env="development", voice_enabled="")
    assert s.voice_on is True


def test_voice_off_in_production():
    s = Settings(app_env="production", voice_enabled="")
    assert s.voice_on is False


def test_voice_can_force_on_in_production():
    s = Settings(app_env="production", voice_enabled="true")
    assert s.voice_on is True


def test_voice_can_force_off_in_development():
    s = Settings(app_env="development", voice_enabled="false")
    assert s.voice_on is False
