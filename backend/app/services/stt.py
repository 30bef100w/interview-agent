"""STT 服务：faster-whisper 本地转写，免费、无网络依赖（模型首用自动下载）。

单例懒加载 + int8 量化；失败由调用方降级（纯文本路径不受影响）。
优先使用 data/whisper-tiny 本地模型（魔搭镜像下载后离线可用），
不存在时回退 settings.whisper_model（huggingface 在线下载）。
"""
import os

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

from pathlib import Path  # noqa: E402

from app.config import settings  # noqa: E402

LOCAL_MODEL_DIR = Path(__file__).resolve().parents[2] / "data" / "whisper-tiny"

_model = None
_model_loaded = False


def _get_model():
    global _model, _model_loaded
    if not _model_loaded:
        from faster_whisper import WhisperModel

        model_path = (
            str(LOCAL_MODEL_DIR)
            if (LOCAL_MODEL_DIR / "model.bin").exists()
            else settings.whisper_model
        )
        _model = WhisperModel(model_path, device="cpu", compute_type="int8")
        _model_loaded = True
    return _model


def transcribe(audio_path: Path) -> str:
    """转写音频文件为中文文本；返回空串表示没识别到内容。"""
    model = _get_model()
    segments, _ = model.transcribe(
        str(audio_path),
        language="zh",
        beam_size=1,
        vad_filter=True,  # 滤掉静音段，降低误识别
    )
    return "".join(seg.text for seg in segments).strip()
