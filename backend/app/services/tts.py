"""TTS 服务：edge-tts 调用微软免费语音合成接口（纯 HTTP，国内可达）。"""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

from edge_tts import Communicate

DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"
_CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "tts_cache"
_MEM: dict[str, bytes] = {}
_MEM_MAX = 32


def cache_key(text: str, voice: str = DEFAULT_VOICE) -> str:
    return hashlib.sha256(f"{voice}\n{text}".encode("utf-8")).hexdigest()


def _remember(key: str, data: bytes) -> bytes:
    if key in _MEM:
        _MEM.pop(key, None)
    elif len(_MEM) >= _MEM_MAX:
        _MEM.pop(next(iter(_MEM)))
    _MEM[key] = data
    return data


def synthesize(text: str, voice: str = DEFAULT_VOICE) -> bytes:
    """合成中文语音，返回 mp3 字节；命中缓存则跳过 edge-tts。"""
    key = cache_key(text, voice)
    hit = _MEM.get(key)
    if hit:
        return hit
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _CACHE_DIR / f"{key}.mp3"
    if path.is_file() and path.stat().st_size > 0:
        return _remember(key, path.read_bytes())
    data = asyncio.run(_stream(Communicate(text, voice)))
    if not data:
        raise RuntimeError("tts empty")
    path.write_bytes(data)
    return _remember(key, data)


async def _stream(com: Communicate) -> bytes:
    chunks = bytearray()
    async for chunk in com.stream():
        if chunk["type"] == "audio":
            chunks.extend(chunk["data"])
    return bytes(chunks)
