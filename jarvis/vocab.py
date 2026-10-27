"""Пользовательский словарь: hotwords для Whisper + автообучение из успешных команд."""

from __future__ import annotations

import json
import re
import threading
from collections import Counter
from pathlib import Path
from typing import Any

from .config import ROOT

VOCAB_PATH = ROOT / "vocab.json"

# Слова, которые не нужно учить (служебные, слишком короткие, числа)
STOP_WORDS = {
    "и", "в", "на", "с", "по", "к", "у", "о", "а", "но", "или", "не", "да", "нет",
    "the", "a", "an", "to", "of", "in", "on", "at", "for", "is", "it",
    "это", "как", "что", "где", "когда", "кто", "зачем",
    "open", "close", "play", "pause", "stop", "next", "prev", "previous",
    "volume", "up", "down", "mute", "unmute", "screenshot", "lock",
    "weather", "time", "date", "system", "info", "search", "google",
    "запусти", "открой", "закрой", "громче", "тише", "скриншот",
    "найди", "погода", "время", "дата", "сверни", "переключи",
    "and", "or", "then", "now", "please", "thank", "you", "me",
    "i", "my", "your", "is", "are", "was", "were",
    "music", "song", "track", "sound", "audio", "video", "photo",
    "file", "folder", "window", "screen", "computer", "system",
    "быть", "есть", "был", "была", "были",
    "музыка", "песня", "трек", "звук", "аудио", "видео", "фото",
    "файл", "папка", "окно", "экран", "компьютер", "система",
}

# Индикаторы неуспешной команды — не учим слова из таких результатов
ERROR_INDICATORS = (
    "ошибка", "отмена", "отменил", "не найден", "не удалось", "не смог",
    "error", "cancelled", "not found", "failed", "мимо",
)

# Начальный словарь — часто используемые слова
DEFAULT_WORDS = [
    "Spotify", "Discord", "Steam", "Chrome", "Firefox", "Edge",
    "YouTube", "Telegram", "WhatsApp", "Zoom", "Teams", "Slack",
    "Ollama", "Jarvis", "Shadow",
    "громче", "тише", "скриншот", "блокировка", "перезагрузка",
    "выключение", "усыпить", "заблокировать", "запусти", "открой",
    "закрой", "сверни", "переключи", "найди", "погода",
    "температура", "прогноз", "время", "дата", "сегодня",
    "louder", "quieter", "screenshot", "lock", "restart", "shutdown",
    "sleep", "minimize", "close", "switch", "search", "weather",
    "temperature", "forecast", "time", "date", "today",
    "Valorant", "Putty", "MCHOSE", "RoundedTB", "Voicemeeter",
    "Blender", "Premiere", "Photoshop", "Arduino",
]

DEFAULT_CORRECTIONS = {
    "jardis": "jarvis",
    "jorvis": "jarvis",
    "jairus": "jarvis",
    "jarvix": "jarvis",
    "shedow": "shadow",
    "shado": "shadow",
    "шэдоу": "шедоу",
    "шадоу": "шедоу",
    "претти": "pretty",
    "пути": "putty",
    "путти": "putty",
    "валорант": "Valorant",
    "валоран": "Valorant",
    "спотифай": "Spotify",
    "дискорд": "Discord",
    "хром": "Chrome",
    "ютуб": "YouTube",
    "стим": "Steam",
    "телеграм": "Telegram",
    "калькулятор": "калькулятор",
}


class Vocabulary:
    """Словарь hotwords для Whisper + автообучение из успешных команд."""

    def __init__(
        self,
        path: Path | None = None,
        enabled: bool = True,
        limit: int = 60,
        min_count: int = 2,
        seed_words: list[str] | None = None,
        exclude_words: set[str] | None = None,
    ) -> None:
        self.path = path or VOCAB_PATH
        self.enabled = enabled
        self.limit = limit
        self.min_count = min_count
        self._lock = threading.Lock()
        self.words: set[str] = set(DEFAULT_WORDS)
        self.corrections: dict[str, str] = dict(DEFAULT_CORRECTIONS)
        self.learned: Counter = Counter()
        self._exclude: set[str] = exclude_words or set()

        if seed_words:
            self.words.update(seed_words)

        self._load()

    # ------------------------------------------------------------------ persistence
    def _load(self) -> None:
        if not self.path.exists():
            self.save()
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("words"):
                self.words = set(data["words"])
            if data.get("corrections"):
                self.corrections = data["corrections"]
            if data.get("learned"):
                self.learned = Counter(data["learned"])
            if data.get("limit"):
                self.limit = int(data["limit"])
        except (OSError, json.JSONDecodeError, ValueError):
            self.save()

    def save(self) -> None:
        with self._lock:
            self._save_unlocked()

    def _save_unlocked(self) -> None:
        data = {
            "words": sorted(self.words),
            "corrections": self.corrections,
            "learned": dict(self.learned),
            "limit": self.limit,
        }
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------ words
    def add_word(self, word: str) -> bool:
        """Добавить слово в словарь вручную. Возвращает True, если добавлено."""
        word = word.strip()
        if not word or len(word) < 2 or not self.enabled:
            return False
        # Проверяем без учёта регистра
        lower_variants = {w.lower() for w in self.words}
        if word.lower() in lower_variants:
            return False
        with self._lock:
            self.words.add(word)
            self._save_unlocked()
            return True

    def remove_word(self, word: str) -> bool:
        """Удалить слово из словаря."""
        word = word.strip()
        with self._lock:
            # Ищем без учёта регистра
            to_remove = None
            for w in self.words:
                if w.lower() == word.lower():
                    to_remove = w
                    break
            if to_remove is not None:
                self.words.discard(to_remove)
                self._save_unlocked()
                return True
        return False

    def add_correction(self, wrong: str, correct: str) -> None:
        """Добавить исправление: wrong → correct."""
        wrong = wrong.strip().lower()
        correct = correct.strip()
        if wrong and correct and wrong != correct:
            with self._lock:
                self.corrections[wrong] = correct
                self._save_unlocked()

    def remove_correction(self, wrong: str) -> bool:
        wrong = wrong.strip().lower()
        if wrong in self.corrections:
            with self._lock:
                del self.corrections[wrong]
                self._save_unlocked()
            return True
        return False

    # ------------------------------------------------------------------ learning
    def learn(self, text: str, success: bool = True) -> None:
        """Автообучение из команды.

        Слова попадают в словарь ТОЛЬКО если команда выполнилась корректно.
        """
        if not self.enabled or not success or not text:
            return
        # Проверяем, не содержит ли результат признаков ошибки
        lower = text.lower()
        if any(ind in lower for ind in ERROR_INDICATORS):
            return

        words = re.findall(r"\w+", text, flags=re.UNICODE)
        with self._lock:
            changed = False
            for word in words:
                if len(word) < 2 or word.lower() in STOP_WORDS:
                    continue
                if word.lower() in self._exclude:
                    continue
                display = word.capitalize() if word.isalpha() else word
                self.learned[display] += 1
                # Если слово встречается min_count+ раз — добавляем в постоянный словарь
                if self.learned[display] >= self.min_count and display not in self.words:
                    self.words.add(display)
                    changed = True
            if changed:
                self._save_unlocked()

    def observe(self, text: str, success: bool = True) -> None:
        """Алиас для learn()."""
        self.learn(text, success=success)

    # ------------------------------------------------------------------ hotwords
    def hotwords(self) -> str:
        """Возвращает строку hotwords для whisper (ограниченная длина)."""
        if not self.enabled:
            return ""
        with self._lock:
            all_words = list(self.words)
            for word, count in self.learned.most_common(30):
                if count >= 2 and word not in all_words:
                    all_words.append(word)
            result = " ".join(all_words[: self.limit])
            return result

    # ------------------------------------------------------------------ corrections
    def correct(self, text: str) -> str:
        """Применяет исправления (ASR ошибки → правильные слова)."""
        if not text or not self.corrections:
            return text
        words = text.split()
        result = []
        for word in words:
            lower = word.lower().strip(".,!?;:")
            if lower in self.corrections:
                result.append(self.corrections[lower])
            else:
                result.append(word)
        return " ".join(result)

    # ------------------------------------------------------------------ info
    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "words": len(self.words),
                "corrections": len(self.corrections),
                "learned": dict(self.learned.most_common(20)),
                "hotwords": self.hotwords(),
            }

    def list_words(self) -> list[str]:
        with self._lock:
            return sorted(self.words)

    def list_corrections(self) -> dict[str, str]:
        with self._lock:
            return dict(self.corrections)
