"""STT 服务：faster-whisper 本地转写（上传兜底路径）。

优先用 settings.whisper_model（默认 small）；仅当模型名为 tiny 且本地
data/whisper-tiny 存在时才用本地 tiny，避免被过小模型锁死。
"""
import os

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

from pathlib import Path  # noqa: E402

from app.config import settings  # noqa: E402

LOCAL_TINY_DIR = Path(__file__).resolve().parents[2] / "data" / "whisper-tiny"

_model = None
_model_loaded = False
_model_key: str | None = None


def _resolve_model_path() -> str:
    name = (settings.whisper_model or "small").strip()
    local_named = Path(__file__).resolve().parents[2] / "data" / f"whisper-{name}"
    if (local_named / "model.bin").exists():
        return str(local_named)
    # 仅 tiny 才回落到仓库自带的 whisper-tiny，防止误用导致「识别离谱」
    if name == "tiny" and (LOCAL_TINY_DIR / "model.bin").exists():
        return str(LOCAL_TINY_DIR)
    return name


def _get_model():
    global _model, _model_loaded, _model_key
    key = _resolve_model_path()
    if _model_loaded and _model_key == key:
        return _model
    from faster_whisper import WhisperModel

    _model = WhisperModel(key, device="cpu", compute_type="int8")
    _model_loaded = True
    _model_key = key
    return _model


def transcribe(audio_path: Path) -> str:
    """转写音频文件为中文文本；返回空串表示没识别到内容。"""
    model = _get_model()
    segments, _ = model.transcribe(
        str(audio_path),
        language="zh",
        beam_size=5,
        best_of=5,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        condition_on_previous_text=False,
        initial_prompt="以下是一段普通话面试口语回答。",
    )
    return "".join(seg.text for seg in segments).strip()
