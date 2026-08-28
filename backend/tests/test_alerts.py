"""飞书告警与 LLM 错误识别单元测试。"""
from app.services.alert_throttle import mark_alert_sent, should_send_alert
from app.services.llm_alert import is_llm_billing_or_auth_error


def test_should_send_alert_respects_cooldown(monkeypatch, tmp_path):
    state_file = tmp_path / "feishu_alert_state.json"
    monkeypatch.setattr("app.services.feishu_notify._STATE_PATH", state_file)
    assert should_send_alert("test_key", 60) is True
    mark_alert_sent("test_key")
    assert should_send_alert("test_key", 60) is False


def test_is_llm_billing_or_auth_error_by_message():
    assert is_llm_billing_or_auth_error(Exception("Insufficient balance")) is True
    assert is_llm_billing_or_auth_error(Exception("timeout connecting")) is False


def test_is_llm_billing_or_auth_error_status_code_message():
    exc = Exception("Error code: 402 - insufficient balance")
    assert is_llm_billing_or_auth_error(exc) is True
