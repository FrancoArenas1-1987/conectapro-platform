from __future__ import annotations

import httpx
from services.api.settings import settings


class LLMError(Exception):
    pass


async def chat_json(system: str, user: str) -> str:
    if not settings.openai_api_key:
        raise LLMError("OPENAI_API_KEY vacío")

    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.openai_model,
        "temperature": 0.0,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
    }

    timeout = httpx.Timeout(settings.openai_timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(url, headers=headers, json=payload)
        if r.status_code >= 400:
            raise LLMError(f"OpenAI error {r.status_code}: {r.text}")
        data = r.json()
        return data["choices"][0]["message"]["content"]
