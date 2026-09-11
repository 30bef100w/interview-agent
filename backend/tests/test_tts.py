from pathlib import Path

from app.services import tts as tts_mod


def test_tts_cache_skips_network(monkeypatch, tmp_path):
    cache_dir = tmp_path / "tts_cache"
    monkeypatch.setattr(tts_mod, "_CACHE_DIR", cache_dir)
    tts_mod._MEM.clear()
    calls = {"n": 0}

    class FakeCom:
        def __init__(self, *args, **kwargs):
            pass

        async def stream(self):
            calls["n"] += 1
            yield {"type": "audio", "data": b"ID3fake"}

    monkeypatch.setattr(tts_mod, "Communicate", FakeCom)
    first = tts_mod.synthesize("你好，欢迎参加面试")
    second = tts_mod.synthesize("你好，欢迎参加面试")
    assert first == b"ID3fake"
    assert second == first
    assert calls["n"] == 1
    files = list(cache_dir.glob("*.mp3"))
    assert len(files) == 1
    tts_mod._MEM.clear()
    third = tts_mod.synthesize("你好，欢迎参加面试")
    assert third == first
    assert calls["n"] == 1
    assert Path(files[0]).read_bytes() == first
