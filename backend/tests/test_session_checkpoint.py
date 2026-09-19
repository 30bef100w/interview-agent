"""会话 checkpoint：无 Redis 时必须走文件兜底，不能 NameError。"""
from app.services.session_checkpoint import load_checkpoint, save_checkpoint


def test_save_checkpoint_without_redis_uses_file(monkeypatch, tmp_path):
    monkeypatch.setattr("app.services.session_checkpoint.get_redis", lambda: None)
    monkeypatch.setattr("app.services.session_checkpoint._CHECKPOINT_DIR", tmp_path)

    seq = save_checkpoint(24, {"stage": "ASKING", "history": []})
    assert seq == 1
    loaded = load_checkpoint(24)
    assert loaded is not None
    assert loaded["seq"] == 1
    assert loaded["stage"] == "ASKING"


def test_save_checkpoint_redis_failure_falls_back_to_file(monkeypatch, tmp_path):
    class Boom:
        def incr(self, *_a, **_k):
            raise RuntimeError("redis down")

    monkeypatch.setattr("app.services.session_checkpoint.get_redis", lambda: Boom())
    monkeypatch.setattr("app.services.session_checkpoint._CHECKPOINT_DIR", tmp_path)

    seq = save_checkpoint(25, {"stage": "ASKING"})
    assert seq == 1
    assert load_checkpoint(25)["seq"] == 1
