"""Ollama client with tool calling."""

from __future__ import annotations

from typing import Any

import requests

from .config import Config
from .tools import Tools

SYSTEM_PROMPT = """You are Jarvis, a voice assistant on the user's Windows computer.
Your answers are spoken aloud, so keep them short: one or two sentences,
no lists, markdown, emoji, or technical details.

Rules:
- Reply in the same language the user uses (Russian or English).
- If the user asks to do something with the computer, call the appropriate tool; do not just explain how.
- For ordinary questions (math, facts, advice) answer yourself, without tools.
- Never fabricate results: call the tool first, then report the outcome.
- Use type_text only when explicitly asked to type or enter text.
- Do not invent data (weather, rates, news): if you have no tool to fetch it, say you do not know.
- If a tool returns an error, briefly say it did not work.
- Answer questions to the point, friendly, use informal "you" (ty in Russian).
- Do not apologize without reason and do not add extra warnings.
"""


class LLM:
    """Ollama client with tool calling."""

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
        except Exception:  # noqa: BLE001 - Ollama may be unavailable
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
        """Warm up the model so the first real request is faster."""
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
        except Exception:  # noqa: BLE001 - warmup failure is not critical
            pass

    # ------------------------------------------------------------------ chat
    def chat(self, text: str, on_tool: Any = None) -> str:
        if not self.available():
            return (
                "Ollama is not running. Please start Ollama and try again: "
                "run `ollama serve` in a terminal."
            )
        if not self.has_model():
            return (
                f"Model {self.model} is not installed. Download it with: "
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
                return "The model took too long to respond. Try a shorter question or a smaller model."
            except Exception as exc:  # noqa: BLE001
                return f"Error talking to Ollama: {type(exc).__name__}."

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
            answer = answer or "I could not finish the task in time, please try again."

        self.history.append({"role": "user", "content": text})
        if answer:
            self.history.append({"role": "assistant", "content": answer})
        self.history = self.history[-self.history_limit :]
        return answer or "Done."