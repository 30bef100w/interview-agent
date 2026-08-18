import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterator, Optional, Protocol

from openai import OpenAI

from app.config import settings
from app.services.llm.manager import estimate_cost

_client: OpenAI | None = None

UsageCallback = Callable[[str, str, int, int, float], None]  # provider, model, in, out, cost_yuan


class LlmPort(Protocol):
    def chat_json(self, system: str, user: str) -> dict: ...
    def chat_json_many(self, calls: list[tuple[str, str]]) -> list[dict]: ...
    def chat_text(self, system: str, user: str) -> str: ...
    def chat_stream(self, system: str, user: str) -> Iterator[str]: ...


def get_openai_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            timeout=60,
        )
    return _client


def _new_client(base_url: str, api_key: str) -> OpenAI:
    return OpenAI(api_key=api_key, base_url=base_url, timeout=90)


class OpenAiLlm:
    """多 provider 适配器：chat_json/chat_json_many/chat_text/chat_stream + usage 记录。

    provider 参数决定 base_url/model/api_key；on_usage 回调用于用量统计。
    """

    def __init__(
        self,
        client: OpenAI | None = None,
        *,
        provider: str = "deepseek",
        model: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        input_price_per_m: float = 1.0,
        output_price_per_m: float = 2.0,
        on_usage: UsageCallback | None = None,
    ) -> None:
        self.provider = provider
        self.model = model or settings.deepseek_model
        self._input_price = input_price_per_m
        self._output_price = output_price_per_m
        self.on_usage = on_usage
        if client is not None:
            self._client = client
        elif base_url and api_key:
            self._client = _new_client(base_url, api_key)
        else:
            self._client = get_openai_client()

    def _record(self, usage) -> None:
        if not usage or not self.on_usage:
            return
        inp = getattr(usage, "prompt_tokens", 0) or 0
        out = getattr(usage, "completion_tokens", 0) or 0
        cost = estimate_cost(inp, out, self._input_price, self._output_price)
        self.on_usage(self.provider, self.model, inp, out, cost)

    def chat_json(self, system: str, user: str, *, max_retries: int = 2) -> dict:
        last_err: Exception | None = None
        for _ in range(max_retries + 1):
            try:
                resp = self._client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    response_format={"type": "json_object"},
                    # 规划/追问需一定多样性；过高易破坏 JSON 稳定
                    temperature=0.5,
                )
                self._record(resp.usage)
                return _parse_json(resp.choices[0].message.content or "")
            except Exception as e:  # noqa: BLE001
                last_err = e
        raise last_err  # type: ignore[misc]

    def chat_json_many(self, calls: list[tuple[str, str]]) -> list[dict]:
        if not calls:
            return []
        with ThreadPoolExecutor(max_workers=min(len(calls), 4)) as pool:
            futures = [pool.submit(self.chat_json, s, u) for s, u in calls]
            return [f.result() for f in futures]

    def chat_text(self, system: str, user: str) -> str:
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.7,
        )
        self._record(resp.usage)
        return (resp.choices[0].message.content or "").strip()

    def chat_stream(self, system: str, user: str) -> Iterator[str]:
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.7,
            stream=True,
            stream_options={"include_usage": True},
        )
        for chunk in resp:
            if chunk.usage:
                self._record(chunk.usage)
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta


class StreamingLlm:
    """装饰 LlmPort：chat_text 逐 token 转发给 on_token（SSE 用），其余方法原样透传。

    引擎逻辑不变，只换 llm 实现即可把面试官消息流式推给客户端。
    """

    def __init__(self, inner: LlmPort, on_token: Callable[[str], None]) -> None:
        self._inner = inner
        self._on_token = on_token

    def chat_json(self, system: str, user: str, **kwargs) -> dict:
        return self._inner.chat_json(system, user, **kwargs)

    def chat_json_many(self, calls: list[tuple[str, str]]) -> list[dict]:
        return self._inner.chat_json_many(calls)

    def chat_text(self, system: str, user: str) -> str:
        parts: list[str] = []
        for token in self._inner.chat_stream(system, user):
            parts.append(token)
            self._on_token(token)
        return "".join(parts).strip()

    def chat_stream(self, system: str, user: str) -> Iterator[str]:
        yield from self._inner.chat_stream(system, user)


def _parse_json(content: str) -> dict:
    content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", content, re.DOTALL)
    if m:
        return json.loads(m.group(0))
    raise ValueError(f"LLM 输出不是有效 JSON: {content[:200]}")


class UsageSink:
    """用法：UsageSink(session_id, user_id, db) → 构造 OpenAiLlm 时传 on_usage=sink.record"""

    def __init__(
        self,
        user_id: int,
        session_id: int | None,
        db,
        *,
        used_platform_key: bool = False,
    ) -> None:
        self._user_id = user_id
        self._session_id = session_id
        self._db = db
        self._used_platform_key = 1 if used_platform_key else 0

    def record(self, provider: str, model: str, inp: int, out: int, cost: float) -> None:
        from app.models.llm_usage import LLMUsage

        self._db.add(
            LLMUsage(
                user_id=self._user_id,
                session_id=self._session_id,
                provider=provider,
                model=model,
                input_tokens=inp,
                output_tokens=out,
                cost_yuan=cost,
                used_platform_key=self._used_platform_key,
            )
        )
