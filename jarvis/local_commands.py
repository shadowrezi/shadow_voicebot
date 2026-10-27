"""Fast local commands: instant, no neural network needed."""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from typing import Callable

from .tools import Tools

EXIT_WORDS_RU = ("выключись", "отключись", "заверши работу", "спать", "пока", "хватит")
EXIT_WORDS_EN = ("shut down", "turn off", "exit", "quit", "goodbye", "bye")

YES_WORDS = {"да", "ага", "угу", "подтверждаю", "выполняй", "конечно", "давай", "ок", "окей", "yes"}
NO_WORDS = {"нет", "не", "отмена", "отмени", "стоп", "no", "неа"}

# ---------------------------------------------------------------------------
# Список часто используемых слов и фраз (для справки и лучшего общения)
# ---------------------------------------------------------------------------
COMMON_WORDS_RU = (
    "привет", "здравствуй", "доброе утро", "добрый день", "добрый вечер",
    "спасибо", "пожалуйста", "извини", "хорошо", "плохо",
    "да", "нет", "возможно", "точно", "пожалуйста",
    "включи", "выключи", "запусти", "открой", "закрой", "заверши", "закрыть",
    "громче", "тише", "звук", "музыка", "трек", "песня",
    "время", "дата", "день", "месяц", "год",
    "погода", "температура", "прогноз",
    "скриншот", "снимок", "файл", "папка", "документ",
    "калькулятор", "браузер", "ютуб", "спотифай", "дискорд", "стим",
    "компьютер", "окно", "рабочий стол", "блокировка",
    "помощь", "команды", "что ты умеешь",
    "повтори", "ещё раз", "что играет", "что сейчас играет",
)

COMMON_WORDS_EN = (
    "hello", "hi", "good morning", "good afternoon", "good evening",
    "thank you", "please", "sorry", "yes", "no", "maybe",
    "turn on", "turn off", "start", "open", "close", "quit", "kill",
    "louder", "quieter", "sound", "music", "track", "song",
    "time", "date", "day", "month", "year",
    "weather", "temperature", "forecast",
    "screenshot", "file", "folder", "document",
    "calculator", "browser", "youtube", "spotify", "discord", "steam",
    "computer", "window", "desktop", "lock",
    "help", "commands", "what can you do",
    "repeat", "again", "what's playing", "what is playing",
)

WAKE_AND_COMMON_RU = {"джарвис", "jarvis", "компьютер"} | set(w.split()[0] for w in COMMON_WORDS_RU)
WAKE_AND_COMMON_EN = {"джарвис", "jarvis", "computer"} | set(w.split()[0] for w in COMMON_WORDS_EN)


def normalize(text: str) -> str:
    text = text.lower().replace("ё", "е")
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return " ".join(text.split())


@dataclass
class Result:
    text: str
    exit: bool = False
    source: str = "local"


class LocalCommands:
    """Разбирает простые фразы без обращения к модели."""

    def __init__(self, tools: Tools) -> None:
        self.tools = tools
        self.lang: str = "ru"
        self._last_result: str | None = None  # для команды «повтори»

        ru_rules: list[tuple[str, Callable[[], str]]] = [
            # --- что играет (проверяется раньше play/pause) ---
            (r"(что играет|что сейчас играет|какая песня|название трека|что сейчас звучит)", lambda: tools.call("media_now_playing", {})),
            # --- музыка в Spotify (с запуском, если не запущен) ---
            (r"(включи музыку в спотифай|включи спотифай|запусти музыку в спотифай|включи музыку spotify|включи spotify)", lambda: self._play_spotify()),
            # --- громкость ---
            (r"(громче|погромче|прибавь (громкость|звук))", lambda: tools.call("volume", {"action": "up"})),
            (r"(тише|потише|убавь (громкость|звук))", lambda: tools.call("volume", {"action": "down"})),
            (r"(выключи звук|заглуши|без звука|беззвучие)", lambda: tools.call("volume", {"action": "mute"})),
            (r"(включи звук|верни звук)", lambda: tools.call("volume", {"action": "mute"})),
            # --- плеер / Spotify ---
            (r"(пауза|на паузу|продолжай|играй|плей|vozобнови|возобнови)", lambda: tools.call("media", {"action": "play_pause"})),
            (r"(включи музыку|включи песню|включи трек)", lambda: tools.call("media", {"action": "play_pause"})),
            (r"(следующий трек|следующая песня|переключи трек|переключи|дальше|следующий|скип|skip)", lambda: tools.call("media", {"action": "next"})),
            (r"(предыдущий трек|предыдущая песня|назад трек|назад|верни|предыдущий)", lambda: tools.call("media", {"action": "prev"})),
            (r"(останови музыку|стоп музыку|стоп трек|стоп музыка)", lambda: tools.call("media", {"action": "stop"})),
            # --- экран ---
            (r"(скриншот|снимок экрана|скрин|сделай снимок)", lambda: tools.call("screenshot", {})),
            # --- компьютер ---
            (r"(заблокируй|блокировка|заблокируй компьютер)", lambda: tools.call("lock_pc", {})),
            (r"(выключи|отключи|заверши работу) (компьютер|пк|систему)|выключение компьютера", lambda: tools.call("power", {"action": "shutdown"})),
            (r"(перезагрузи|перезапусти|рестарт) (компьютер|пк|систему)|перезагрузка компьютера", lambda: tools.call("power", {"action": "restart"})),
            (r"(сверни все окна|сверни все|покажи рабочий стол)", lambda: tools.call("window", {"action": "minimize_all"})),
            (r"(закрой окно|закрой это|закрой приложение)", lambda: tools.call("window", {"action": "close"})),
            (r"(переключи окно|следующее окно|альт таб)", lambda: tools.call("window", {"action": "switch"})),
            # --- приложения: браузер и ютуб (быстрый запуск) ---
            (r"^(браузер|хром|chrome|firefox|файрфокс|edge|эдж)$", lambda: tools.call("open_app", {"name": phrase})),
            (r"^(ютуб|youtube|ютуб)$", lambda: tools.call("open_app", {"name": "ютуб"})),
            (r"^(ютуб мьюзик|youtube music)$", lambda: tools.call("open_app", {"name": "ютуб мьюзик"})),
            (r"(какое число|какая дата|какой сегодня день|скажи дату)", lambda: tools.call("get_time", {})),
            # --- система ---
            (r"(информация о системе|характеристики компьютера|что за железо)", lambda: tools.call("system_info", {})),
        ]
        en_rules: list[tuple[str, Callable[[], str]]] = [
            # --- media now playing (check before play/pause) ---
            (r"(what.?s playing|what is playing|current song|now playing|what song)", lambda: tools.call("media_now_playing", {})),
            # --- music in Spotify (launch if not running) ---
            (r"(play music in spotify|play spotify|start spotify|play spotify music)", lambda: self._play_spotify()),
            # --- volume ---
            (r"(louder|volume up|turn it up|increase volume)", lambda: tools.call("volume", {"action": "up"})),
            (r"(quieter|volume down|turn it down|decrease volume)", lambda: tools.call("volume", {"action": "down"})),
            (r"(mute|unmute|turn off sound|turn on sound|silence)", lambda: tools.call("volume", {"action": "mute"})),
            # --- player / Spotify ---
            (r"(pause|play|resume|play music|play spotify|play a song)", lambda: tools.call("media", {"action": "play_pause"})),
            (r"(next track|next song|skip|skip track|forward|next|next one)", lambda: tools.call("media", {"action": "next"})),
            (r"(previous track|previous song|back track|back|go back|rewind|previous)", lambda: tools.call("media", {"action": "prev"})),
            (r"(stop music|stop track|stop the music)", lambda: tools.call("media", {"action": "stop"})),
            # --- screen ---
            (r"(screenshot|screen capture|take a screenshot|capture screen)", lambda: tools.call("screenshot", {})),
            # --- computer ---
            (r"(lock|lock computer|lock pc)", lambda: tools.call("lock_pc", {})),
            (r"(shut down|shutdown|turn off|power off) (?:(?:the|my|your) )?(computer|pc|system)", lambda: tools.call("power", {"action": "shutdown"})),
            (r"(restart|reboot) (?:(?:the|my|your) )?(computer|pc|system)", lambda: tools.call("power", {"action": "restart"})),
            (r"(minimize all|show desktop|minimise all)", lambda: tools.call("window", {"action": "minimize_all"})),
            (r"(close window|close this|close app)", lambda: tools.call("window", {"action": "close"})),
            (r"(switch window|next window|alt tab)", lambda: tools.call("window", {"action": "switch"})),
            # --- apps: browser and youtube (quick launch) ---
            (r"^(browser|chrome|firefox|edge)$", lambda: tools.call("open_app", {"name": phrase})),
            (r"^(youtube|yt)$", lambda: tools.call("open_app", {"name": "youtube"})),
            (r"^(youtube music)$", lambda: tools.call("open_app", {"name": "youtube music"})),
            # --- time/date ---
            (r"(what time|what.?s the time|current time|tell me the time)", lambda: tools.call("get_time", {})),
            (r"(what date|what.?s the date|today.?s date|what day|tell me the date)", lambda: tools.call("get_time", {})),
            # --- system ---
            (r"(system info|computer specs|specs|system information)", lambda: tools.call("system_info", {})),
        ]
        self.ru_rules = [(re.compile(pattern), action) for pattern, action in ru_rules]
        self.en_rules = [(re.compile(pattern), action) for pattern, action in en_rules]

    # ------------------------------------------------------------------ spotify
    def _play_spotify(self) -> str:
        """Запускает Spotify (если не запущен) и включает музыку."""
        def _is_running() -> bool:
            try:
                completed = subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     "Get-Process spotify -ErrorAction SilentlyContinue | Select-Object -First 1 | Out-Null; if ($?) { 'running' } else { 'not' }"],
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
                )
                return (completed.stdout or "").strip() == "running"
            except Exception:  # noqa: BLE001
                return False

        if not _is_running():
            try:
                self.tools.call("open_app", {"name": "spotify"})
            except Exception as exc:  # noqa: BLE001
                return self.tools._t(f"Не удалось запустить Spotify: {exc}", f"Failed to start Spotify: {exc}")
            # ждём запуска (до 10 секунд)
            for _ in range(20):
                time.sleep(0.5)
                if _is_running():
                    break
            time.sleep(1.0)

        result = self.tools.call("media", {"action": "play_pause"})
        return self.tools._t("Включил музыку в Spotify", "Playing music in Spotify") + f" ({result})"

    # ------------------------------------------------------------------ api
    def handle(self, text: str) -> Result | None:
        phrase = normalize(text)
        if not phrase:
            return None

        exit_words = EXIT_WORDS_RU if self.lang == "ru" else EXIT_WORDS_EN
        # Точное совпадение: «exit spotify» не должно трактоваться как выход
        # из ассистента — это команда закрытия приложения.
        if phrase in exit_words:
            text = "Shutting down. Call me if you need anything."
            return Result(text, exit=True)

        # --- повторить последний ответ ---
        if phrase in ("повтори", "повтори ещё раз", "ещё раз", "repeat", "again", "repeat that", "say again"):
            if self._last_result:
                return Result(self._last_result)
            return Result("Nothing to repeat.")

        rules = self.ru_rules if self.lang == "ru" else self.en_rules
        for pattern, action in rules:
            if pattern.search(phrase):
                result_text = action()
                self._last_result = result_text
                return Result(result_text)

        # --- закрытие приложений: «закрой/exit/close <имя>» ---
        close_verbs_ru = r"(?:закрой|закрыть|выключи|выключить|заверши|завершить)"
        close_verbs_en = r"(?:close|exit|quit|kill|stop)"
        close_match_ru = re.match(rf"{close_verbs_ru}\s+(.+)$", phrase)
        close_match_en = re.match(rf"{close_verbs_en}\s+(.+)$", phrase)
        close_match = close_match_ru if self.lang == "ru" else close_match_en
        if close_match:
            target = close_match.group(1).strip()
            # «закрой окно/это/приложение» уже обработано правилом выше
            if target not in {"окно", "это", "приложение", "window", "this", "app"}:
                result = self.tools.call("close_app", {"name": target})
                self._last_result = result
                return Result(result)

        open_match = re.match(r"(?:открой|запусти|включи|открыть)\s+(.+)$", phrase)
        if open_match:
            target = open_match.group(1).strip()
            if target in {"что", "нибудь"}:
                return None
            if "." in target and " " not in target:
                result = self.tools.call("open_url", {"url": target})
                self._last_result = result
                return Result(result)
            result = self.tools.call("open_app", {"name": target})
            self._last_result = result
            return Result(result)

        open_en = re.match(r"(?:open|launch|start|play)\s+(.+)$", phrase)
        if open_en:
            target = open_en.group(1).strip()
            if target in {"something", "anything"}:
                return None
            if "." in target and " " not in target:
                result = self.tools.call("open_url", {"url": target})
                self._last_result = result
                return Result(result)
            result = self.tools.call("open_app", {"name": target})
            self._last_result = result
            return Result(result)

        search_match = re.match(r"(?:найди|загугли|поищи)\s+(.+)$", phrase)
        if search_match:
            result = self.tools.call("web_search", {"query": search_match.group(1)})
            self._last_result = result
            return Result(result)

        search_en = re.match(r"(?:search|google|look up)\s+(.+)$", phrase)
        if search_en:
            result = self.tools.call("web_search", {"query": search_en.group(1)})
            self._last_result = result
            return Result(result)

        weather_match = re.match(r"погода\s+(?:в\s+)?(.+)$", phrase)
        if weather_match:
            result = self.tools.call("get_weather", {"city": weather_match.group(1)})
            self._last_result = result
            return Result(result)

        weather_en = re.match(r"(?:weather in|weather for)\s+(.+)$", phrase)
        if weather_en:
            result = self.tools.call("get_weather", {"city": weather_en.group(1)})
            self._last_result = result
            return Result(result)

        # --- управление словарём ---
        remember_ru = re.match(r"(?:запомни слово|запомни|добавь слово)\s+(.+)$", phrase)
        if remember_ru:
            word = remember_ru.group(1).strip()
            if hasattr(self.tools, "vocab"):
                result = self.tools.vocab.add_word(word)
                if result:
                    msg = f"Remembered word '{word}'."
                    self._last_result = msg
                    return Result(msg)
                msg = f"Word '{word}' is already in the vocabulary."
                self._last_result = msg
                return Result(msg)

        remember_en = re.match(r"(?:remember word|remember|add word)\s+(.+)$", phrase)
        if remember_en:
            word = remember_en.group(1).strip()
            if hasattr(self.tools, "vocab"):
                result = self.tools.vocab.add_word(word)
                if result:
                    msg = f"Remembered word «{word}»."
                    self._last_result = msg
                    return Result(msg)
                msg = f"Word «{word}» is already in vocabulary."
                self._last_result = msg
                return Result(msg)

        forget_ru = re.match(r"(?:забудь слово|забудь|удали слово)\s+(.+)$", phrase)
        if forget_ru:
            word = forget_ru.group(1).strip()
            if hasattr(self.tools, "vocab"):
                result = self.tools.vocab.remove_word(word)
                if result:
                    msg = f"Removed word '{word}' from the vocabulary."
                    self._last_result = msg
                    return Result(msg)
                msg = f"Word '{word}' is not in the vocabulary."
                self._last_result = msg
                return Result(msg)

        forget_en = re.match(r"(?:forget word|forget|remove word)\s+(.+)$", phrase)
        if forget_en:
            word = forget_en.group(1).strip()
            if hasattr(self.tools, "vocab"):
                result = self.tools.vocab.remove_word(word)
                if result:
                    msg = f"Removed word «{word}» from vocabulary."
                    self._last_result = msg
                    return Result(msg)
                msg = f"Word «{word}» is not in vocabulary."
                self._last_result = msg
                return Result(msg)

        vocab_info_ru = re.match(r"(?:какие слова|словарь|слова в словаре|покажи словарь)$", phrase)
        if vocab_info_ru:
            if hasattr(self.tools, "vocab"):
                words = self.tools.vocab.list_words()
                msg = f"Vocabulary has {len(words)} words: {', '.join(words[:20])}{'...' if len(words) > 20 else ''}."
                self._last_result = msg
                return Result(msg)

        vocab_info_en = re.match(r"(?:what words|vocabulary|words in vocab|show vocabulary)$", phrase)
        if vocab_info_en:
            if hasattr(self.tools, "vocab"):
                words = self.tools.vocab.list_words()
                msg = f"Vocabulary has {len(words)} words: {', '.join(words[:20])}{'...' if len(words) > 20 else ''}."
                self._last_result = msg
                return Result(msg)

        help_match = re.match(r"(что ты умеешь|список команд|помощь|команды)$", phrase)
        if help_match:
            return Result(HELP_TEXT_RU)

        help_en = re.match(r"(what can you do|list of commands|help|commands)$", phrase)
        if help_en:
            return Result(HELP_TEXT_EN)

        return None


HELP_TEXT_RU = (
    "I can open apps and websites ('open chrome'), close apps "
    "('close spotify', 'exit discord', 'close chrome'), control volume and media, take screenshots, "
    "check weather, lock the PC, search the web, read and write files, "
    "run PowerShell commands and answer questions. Everything else goes through the local neural network."
)

HELP_TEXT_EN = (
    "I can open apps and websites, control volume and media, take screenshots, check the "
    "weather, lock the computer, search the web, read and write files, run PowerShell commands, "
    "and answer questions. Everything else goes through the local neural network."
)
