"""Конфигурация ассистента: значения по умолчанию + config.json."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
LOG_DIR = ROOT / "logs"

DEFAULTS: dict[str, Any] = {
    "assistant_name": "Shadow",
    "wake_words": [
        "shadow", "шедоу", "шэдоу", "шадоу",
        "джарвис", "jarvis", "компьютер",
    ],
    "require_wake_word": False,
    "audio": {
        "device": None,
        "sample_rate": 16000,
        "silence_ms": 500,
        "max_phrase_s": 15,
        "min_rms": 150,
        "pre_roll_ms": 200,
        "wake_word_enabled": False,
        "continuous_conversation": False,
        "conversation_timeout": 8.0,
    },
    "asr": {
        "model": "small",
        "device": "auto",
        "compute_type": "auto",
        "language": None,
        "beam_size": 1,
        "learn_words": True,
        "hotwords": [],
        "hotwords_limit": 40,
        "hotwords_min_count": 2,
    },
    "tts": {
        "enabled": True,
        "engine": "edge",
        "voice": "ru-RU-SvetlanaNeural",
        "rate": "+12%",
        "pitch": "+120Hz",
        "volume": "+0%",
    },
    "llm": {
        "base_url": "http://127.0.0.1:11434",
        "model": "qwen3:8b",
        "temperature": 0.3,
        "think": True,
        "max_tool_rounds": 5,
        "timeout_s": 240,
        "history_messages": 12,
    },
    "safety": {
        "confirm_destructive": True,
        "audit_log": True,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Рекурсивно накладывает override на base."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class Config:
    """Доступ к настройкам через атрибуты и пути."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or CONFIG_PATH
        self.data = copy.deepcopy(DEFAULTS)
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8-sig"))
                self.data = _deep_merge(self.data, loaded)
            except (OSError, json.JSONDecodeError) as exc:
                print(f"[config] не удалось прочитать {self.path}: {exc}")
        else:
            self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def section(self, name: str) -> dict[str, Any]:
        return self.data.setdefault(name, {})

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, dotted: str, value: Any) -> None:
        parts = dotted.split(".")
        node = self.data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
