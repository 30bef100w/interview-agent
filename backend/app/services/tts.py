"""TTS 服务：edge-tts 调用微软免费语音合成接口（纯 HTTP，国内可达）。"""
import asyncio

from edge_tts import Communicate

DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"


def synthesize(text: str, voice: str = DEFAULT_VOICE) -> bytes:
    """合成中文语音，返回 mp3 字节；失败抛错由调用方降级。"""
    return asyncio.run(_stream(Communicate(text, voice)))


async def _stream(com: Communicate) -> bytes:
    chunks = bytearray()
    async for chunk in com.stream():
        if chunk["type"] == "audio":
            chunks.extend(chunk["data"])
    return bytes(chunks)
