"""语音接口：转写（录音 → 文本，前端预览确认后走正常 answer 接口）+ 语音合成。"""
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse

from app.api.deps import get_current_user
from app.models import User
from app.services.stt import transcribe
from app.services.tts import synthesize

router = APIRouter(prefix="/api/voice", tags=["voice"])

ALLOWED_AUDIO = {".webm", ".mp3", ".wav", ".m4a", ".ogg"}
MAX_AUDIO_BYTES = 10 * 1024 * 1024  # 10MB 上限（约 1 分钟录音）


@router.post("/transcribe")
def transcribe_audio(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
) -> dict:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_AUDIO:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="不支持的音频格式"
        )
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="音频为空")
    if len(content) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="音频超过 1 分钟，请分段录制")

    tmp = Path(tempfile.gettempdir()) / f"{uuid.uuid4().hex}{suffix}"
    tmp.write_bytes(content)
    try:
        text = transcribe(tmp)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="语音转写失败，请改用文字输入"
        )
    finally:
        tmp.unlink(missing_ok=True)

    if not text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="没有识别到语音内容")
    return {"text": text}


@router.get("/tts")
def text_to_speech(
    text: str,
    current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    text = text.strip()
    if not text or len(text) > 500:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文本长度不合法")
    try:
        audio = synthesize(text)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="语音合成失败，请使用文字模式"
        )
    return StreamingResponse(iter([audio]), media_type="audio/mpeg")
