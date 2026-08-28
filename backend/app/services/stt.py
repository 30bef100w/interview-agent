"""STT 服务：faster-whisper 本地转写（上传兜底 / Web Speech 失败回退）。"""
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
    if name == "tiny" and (LOCAL_TINY_DIR / "model.bin").exists():
        return str(LOCAL_TINY_DIR)
    return name


def _device_and_compute() -> tuple[str, str]:
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda", "float16"
    except Exception:  # noqa: BLE001
        pass
    return "cpu", "int8"


def _get_model():
    global _model, _model_loaded, _model_key
    key = _resolve_model_path()
    if _model_loaded and _model_key == key:
        return _model
    from faster_whisper import WhisperModel

    device, compute_type = _device_and_compute()
    _model = WhisperModel(key, device=device, compute_type=compute_type)
    _model_loaded = True
    _model_key = key
    return _model


def transcribe(
    audio_path: Path,
    *,
    language: str = "zh",
    prompt: str = "",
) -> str:
    """转写音频文件；返回空串表示没识别到内容。"""
    model = _get_model()
    hint = (prompt or "").strip() or "以下是一段普通话技术面试口语回答，可能包含 Redis、Kafka、微服务、算法等术语。"
    segments, _ = model.transcribe(
        str(audio_path),
        language=language or "zh",
        beam_size=5,
        best_of=5,
        vad_filter=True,
        vad_parameters={
            "min_silence_duration_ms": 350,
            "speech_pad_ms": 120,
        },
        condition_on_previous_text=False,
        initial_prompt=hint,
        temperature=0.0,
    )
    return "".join(seg.text for seg in segments).strip()
