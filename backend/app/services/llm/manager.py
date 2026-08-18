"""LLM 多 provider 管理：配置加载、key 加密、用量换算、按用户配置构造 client。

- 预置 provider：DeepSeek / 智谱 GLM / 通义千问 / 字节豆包 / 硅基流动（均 OpenAI 兼容）
- 用户可在设置页配自己的 key + 选模型；未配置的用户走系统默认 key（管理员兜底）
- 每次调用记录 usage（token + 金额），按模型单价表换算
"""
import json
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

_DATA_DIR = Path(__file__).resolve().parents[3] / "data"


@lru_cache(maxsize=1)
def load_providers() -> dict:
    with open(_DATA_DIR / "llm_providers.json", encoding="utf-8") as f:
        return json.load(f)


def list_providers() -> list[dict]:
    """预置 provider 列表（不含 key）。"""
    return [
        {"id": p["id"], "name": p["name"], "base_url": p["base_url"], "models": p["models"]}
        for p in load_providers()["providers"]
    ]


def find_provider(provider_id: str) -> dict | None:
    return next(
        (p for p in load_providers()["providers"] if p["id"] == provider_id), None
    )


def find_model(provider_id: str, model_id: str) -> dict | None:
    p = find_provider(provider_id)
    if not p:
        return None
    return next((m for m in p["models"] if m["id"] == model_id), None)


def _fernet() -> Fernet:
    # 用 jwt_secret 派生密钥（够用；生产可换独立 SECRET）
    import hashlib

    key = hashlib.sha256(settings.jwt_secret.encode()).digest()
    return Fernet(__import__("base64").b64encode(key))


def encrypt_key(plain: str) -> str:
    if not plain:
        return ""
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_key(encrypted: str) -> str:
    if not encrypted:
        return ""
    try:
        return _fernet().decrypt(encrypted.encode()).decode()
    except InvalidToken:
        return ""


def resolve_llm_config(
    user_provider: str, user_model: str, user_key_encrypted: str, use_default: bool
) -> dict:
    """解析用户的 LLM 配置 → (base_url, api_key, model, provider, input_price, output_price)。

    用户未配 key（use_default）→ 系统默认 DeepSeek key 兜底。
    """
    p = find_provider(user_provider or "deepseek")
    if not p:
        p = find_provider("deepseek")
    model = find_model(p["id"], user_model) or p["models"][0]
    if use_default or not user_key_encrypted:
        api_key = settings.deepseek_api_key
        base_url = settings.deepseek_base_url
        model_id = settings.deepseek_model
        m = find_model("deepseek", model_id) or {"input_price_per_m": 1.0, "output_price_per_m": 2.0}
    else:
        api_key = decrypt_key(user_key_encrypted)
        base_url = p["base_url"]
        model_id = model["id"]
        m = model
    return {
        "provider": p["id"],
        "model": model_id,
        "base_url": base_url,
        "api_key": api_key,
        "input_price_per_m": m["input_price_per_m"],
        "output_price_per_m": m["output_price_per_m"],
    }


def estimate_cost(input_tokens: int, output_tokens: int, input_price_per_m: float, output_price_per_m: float) -> float:
    """token → 金额（元）。"""
    return round(
        input_tokens / 1_000_000 * input_price_per_m
        + output_tokens / 1_000_000 * output_price_per_m,
        6,
    )
