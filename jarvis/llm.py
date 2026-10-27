"""Локальная нейросеть через Ollama: диалог + вызов инструментов."""

from __future__ import annotations

from typing import Any

import requests

from .config import Config
from .tools import Tools

SYSTEM_PROMPT = """Ты — Джарвис, голосовой ассистент на компьютере пользователя (Windows).
Твои ответы озвучиваются голосом, поэтому говори кратко: одно-два предложения,
без списков, markdown, эмодзи и технических подробностей.

Правила:
- Отвечай на том же языке, на котором спрашивает пользователь (русский или английский). Если пользователь пишет по-английски — отвечай по-английски, если по-русски — по-русски.
- Если просят что-то сделать с компьютером — вызывай подходящий инструмент, а не рассказывай, как это сделать.
- На обычные вопросы (арифметика, факты, советы) отвечай сам, без инструментов.
- Никогда не выдумывай результат действия: сначала вызови инструмент, потом сообщи итог.
- Инструмент type_text используй только когда явно просят напечатать или ввести текст.
- Не придумывай данные (погоду, курсы, новости): если у тебя нет инструмента, который вернёт данные, скажи, что не знаешь.
- Если инструмент вернул ошибку, коротко скажи, что не получилось.
- На вопросы отвечай по существу, дружелюбно, обращайся на «ты».
- Не извиняйся без причины и не добавляй лишних предупреждений.

You are Jarvis, a voice assistant on the user's Windows computer.
Your answers are spoken aloud, so keep them short: one or two sentences,
no lists, markdown, emoji, or technical details.

Rules:
- Reply in the same language the user uses (Russian or English).
- If the user asks to do something with the computer — call the appropriate tool, don't just explain how.
- For ordinary questions (math, facts, advice) answer yourself, without tools.
- Never fabricate results: call the tool first, then report the outcome.
- Use type_text only when explicitly asked to type or enter text.
- Don't invent data (weather, rates, news): if you have no tool to fetch it, say you don't know.
- If a tool returns an error, briefly say it didn't work.
- Answer questions to the point, friendly, use «ты» (informal you).
- Don't apologise without reason and don't add extra warnings.
"""


class LLM:
    """Клиент Ollama с поддержкой tool calling."""

    def __init__(self, config: Config, tools: Tools) -> None:
        self.config = config
        self.tools = tools
        self.base_url = str(config.get("llm.base_url", "http://127.0.0.1:11434")).rstrip("/")
        self.model = str(config.get("llm.model", "qwen3:8b"))
        self.temperature = float(config.get("llm.temperature", 0.3))
        self.max_rounds = int(config.get("llm.max_tool_rounds", 5))
        self.timeout = int(config.get("llm.timeout_s", 180))
        self.think = bool(config.get("llm.think", False))
        self.history_limit = int(config.get("llm.history_messages", 12))
        self.history: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ health
    def models(self) -> list[str]:
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            response.raise_for_status()
            return [item["name"] for item in response.json().get("models", [])]
        except Exception:  # noqa: BLE001 — статус-проверка не должна падать
            return []

    def available(self) -> bool:
        try:
            return requests.get(f"{self.base_url}/api/tags", timeout=3).ok
        except Exception:  # noqa: BLE001
            return False

    def has_model(self) -> bool:
        name = self.model
        variants = {name, f"{name}:latest"}
        return any(m in variants or m.startswith(name + ":") for m in self.models())

    def reset(self) -> None:
        self.history.clear()

    def warmup(self) -> None:
        """Заранее загружает модель в память, чтобы первый ответ не ждал минуту."""
        try:
            requests.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": "ok"}],
                    "stream": False,
                    "think": self.think,
                    "keep_alive": "30m",
                    "options": {"num_predict": 1, "temperature": 0},
                },
                timeout=180,
            )
        except Exception:  # noqa: BLE001 — прогрев необязателен
            pass

    # ------------------------------------------------------------------ chat
    def chat(self, text: str, on_tool: Any = None) -> str:
        if not self.available():
            return (
                "Не могу связаться с локальной моделью. Проверь, что Ollama запущена: "
                "в трее должен быть её значок."
            )
        if not self.has_model():
            return (
                f"Модель {self.model} не найдена. Выполни в терминале: "
                f"ollama pull {self.model}"
            )

        messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(self.history[-self.history_limit :])
        messages.append({"role": "user", "content": text})

        answer = ""
        for round_index in range(self.max_rounds + 1):
            payload: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "tools": self.tools.schemas(),
                "think": self.think,
                "keep_alive": "30m",
                "options": {"temperature": self.temperature},
            }
            try:
                response = requests.post(
                    f"{self.base_url}/api/chat", json=payload, timeout=self.timeout
                )
                response.raise_for_status()
                message = response.json().get("message", {})
            except requests.Timeout:
                return "Модель думает слишком долго. Попробуй переформулировать короче."
            except Exception as exc:  # noqa: BLE001
                return f"Ошибка обращения к модели: {type(exc).__name__}."

            tool_calls = message.get("tool_calls") or []
            content = (message.get("content") or "").strip()
            if content:
                answer = content

            if not tool_calls:
                break

            messages.append(
                {"role": "assistant", "content": content, "tool_calls": tool_calls}
            )
            for call in tool_calls:
                function = call.get("function", {})
                name = function.get("name", "")
                arguments = function.get("arguments") or {}
                if isinstance(arguments, str):
                    try:
                        import json

                        arguments = json.loads(arguments)
                    except ValueError:
                        arguments = {}
                if on_tool:
                    on_tool(name, arguments)
                result = self.tools.call(name, arguments)
                messages.append(
                    {"role": "tool", "content": result, "tool_name": name}
                )
        else:
            answer = answer or "Слишком много шагов подряд, остановился."

        self.history.append({"role": "user", "content": text})
        if answer:
            self.history.append({"role": "assistant", "content": answer})
        self.history = self.history[-self.history_limit :]
        return answer or "Готово."
