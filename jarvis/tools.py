"""Инструменты управления ПК + слой безопасности."""

from __future__ import annotations

import ctypes
import json
import os
import re
import subprocess
import time
import webbrowser
import requests
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from pynput.keyboard import Controller as KeyboardController
from pynput.keyboard import Key

from .config import Config, LOG_DIR

# ---------------------------------------------------------------------------
# Разрушительные команды: не выполняются даже с подтверждением.
# ---------------------------------------------------------------------------
FORBIDDEN_PATTERNS = [
    r"format\s+[a-z]:",
    r"\bdiskpart\b",
    r"\bbcdedit\b",
    r"vssadmin\s+delete",
    r"cipher\s+/w",
    r"remove-item\s+.*-recurse.*(c:\\windows|c:\\users|c:\\\s*$|c:\\\*)",
    r"\brd\s+/s\s+c:\\",
    r"\bdel\s+/[fsq]\b.*c:\\",
    r"\brm\s+-rf\s+/(\s|$)",
    r"\bmkfs\b",
    r"net\s+user\s+\S+\s+/delete",
    r"reg\s+delete\s+hklm",
    r"takeown\s+/f\s+c:\\windows",
]

# Команды, которые можно запускать без голосового подтверждения.
SAFE_SHELL = re.compile(
    r"^\s*(dir|ls|pwd|cd|where|whoami|hostname|ipconfig|systeminfo|tasklist|"
    r"get-[a-z]+|echo|type|findstr|git\s+(status|log|diff|branch)|"
    r"python\s+--version|pip\s+(list|show)|node\s+--version|"
    r"winget\s+list|ollama\s+(list|ps)|nvidia-smi|ping\s+-n\s+[1-4])\b",
    re.IGNORECASE,
)

APP_ALIASES = {
    "хром": "chrome",
    "chrome": "chrome",
    "браузер": "chrome",
    "browser": "chrome",
    "firefox": "firefox",
    "файрфокс": "firefox",
    "фераерфокс": "firefox",
    "фаеерфокс": "firefox",
    "edge": "msedge",
    "эдж": "msedge",
    "стим": "steam://open/main",
    "steam": "steam://open/main",
    "дискорд": "discord://",
    "discord": "discord://",
    "телеграм": "tg://",
    "телеграмм": "tg://",
    "telegram": "tg://",
    "проводник": "explorer",
    "explorer": "explorer",
    "блокнот": "notepad",
    "notepad": "notepad",
    "калькулятор": "calc",
    "calc": "calc",
    "calculator": "calc",
    "терминал": "wt",
    "консоль": "powershell",
    "powershell": "powershell",
    "диспетчер": "taskmgr",
    "taskmgr": "taskmgr",
    "настройки": "ms-settings:",
    "spotify": "spotify:",
    "спотифай": "spotify:",
    "vs code": "code",
    "вс код": "code",
    "vscode": "code",
    "код": "code",
    "ютуб": "https://www.youtube.com",
    "youtube": "https://www.youtube.com",
    "яндекс": "https://ya.ru",
    "почта": "https://mail.google.com",
    "гитхаб": "https://github.com",
    "github": "https://github.com",
    "аризона": "https://arizona-rp.com",
    # --- популярные приложения этого ПК ---
    "paint": "mspaint",
    "пэйнт": "mspaint",
    "рисование": "mspaint",
    "ножницы": "SnippingTool",
    "snipping": "SnippingTool",
    "скриншот инструмент": "SnippingTool",
    "панель управления": "control",
    "control panel": "control",
    "командная строка": "cmd",
    "реестр": "regedit",
    "regedit": "regedit",
    "эпик": "\"C:\\Program Files\\Epic Games\\Launcher\\Portal\\Binaries\\Win64\\EpicGamesLauncher.exe\"",
    "epic": "\"C:\\Program Files\\Epic Games\\Launcher\\Portal\\Binaries\\Win64\\EpicGamesLauncher.exe\"",
    "epic games": "\"C:\\Program Files\\Epic Games\\Launcher\\Portal\\Binaries\\Win64\\EpicGamesLauncher.exe\"",
    "everything": "\"C:\\Program Files\\Everything\\Everything.exe\"",
    "все": "\"C:\\Program Files\\Everything\\Everything.exe\"",
    "всё": "\"C:\\Program Files\\Everything\\Everything.exe\"",
    "поиск файлов": "\"C:\\Program Files\\Everything\\Everything.exe\"",
    "flow launcher": "\"C:\\Users\\shadowrezi\\AppData\\Local\\FlowLauncher\\Flow.Launcher.exe\"",
    "флоу": "\"C:\\Users\\shadowrezi\\AppData\\Local\\FlowLauncher\\Flow.Launcher.exe\"",
    "localsend": "\"C:\\Users\\shadowrezi\\AppData\\Local\\Programs\\LocalSend\\localsend_app.exe\"",
    "локалсенд": "\"C:\\Users\\shadowrezi\\AppData\\Local\\Programs\\LocalSend\\localsend_app.exe\"",
    "quicklook": "\"C:\\Program Files\\QuickLook\\QuickLook.exe\"",
    "квиклук": "\"C:\\Program Files\\QuickLook\\QuickLook.exe\"",
    "нвидиа": "\"C:\\Program Files\\NVIDIA Corporation\\NVIDIA App\\CEF\\NVIDIA App.exe\"",
    "nvidia": "\"C:\\Program Files\\NVIDIA Corporation\\NVIDIA App\\CEF\\NVIDIA App.exe\"",
    "nvidia app": "\"C:\\Program Files\\NVIDIA Corporation\\NVIDIA App\\CEF\\NVIDIA App.exe\"",
    "олама": "\"C:\\Users\\shadowrezi\\AppData\\Local\\Programs\\Ollama\\ollama app.exe\"",
    "ollama": "\"C:\\Users\\shadowrezi\\AppData\\Local\\Programs\\Ollama\\ollama app.exe\"",
    "валорант": "\"D:\\Riot Games\\Riot Client\\RiotClientServices.exe\" --launch-product=valorant --launch-patchline=live",
    "valorant": "\"D:\\Riot Games\\Riot Client\\RiotClientServices.exe\" --launch-product=valorant --launch-patchline=live",
    "рает": "\"D:\\Riot Games\\Riot Client\\RiotClientServices.exe\"",
    "раёт": "\"D:\\Riot Games\\Riot Client\\RiotClientServices.exe\"",
    "riot": "\"D:\\Riot Games\\Riot Client\\RiotClientServices.exe\"",
    "riot client": "\"D:\\Riot Games\\Riot Client\\RiotClientServices.exe\"",
    "осу": "\"C:\\Users\\shadowrezi\\AppData\\Local\\osulazer\\current\\osu!.exe\"",
    "osu": "\"C:\\Users\\shadowrezi\\AppData\\Local\\osulazer\\current\\osu!.exe\"",
    "роблокс": "\"C:\\Users\\shadowrezi\\AppData\\Local\\Roblox\\Versions\\version-9ac8595712b447a7\\RobloxPlayerBeta.exe\"",
    "roblox": "\"C:\\Users\\shadowrezi\\AppData\\Local\\Roblox\\Versions\\version-9ac8595712b447a7\\RobloxPlayerBeta.exe\"",
    "ютуб мьюзик": "\"C:\\Users\\shadowrezi\\AppData\\Local\\Programs\\YouTube Music for Desktop\\ytmdesktop.exe\"",
    "youtube music": "\"C:\\Users\\shadowrezi\\AppData\\Local\\Programs\\YouTube Music for Desktop\\ytmdesktop.exe\"",
    "ардуино": "\"C:\\Users\\shadowrezi\\AppData\\Local\\Programs\\Arduino IDE\\Arduino IDE.exe\"",
    "arduino": "\"C:\\Users\\shadowrezi\\AppData\\Local\\Programs\\Arduino IDE\\Arduino IDE.exe\"",
    "опенкод": "\"C:\\Users\\shadowrezi\\AppData\\Local\\Programs\\@opencodedesktop\\OpenCode.exe\"",
    "opencode": "\"C:\\Users\\shadowrezi\\AppData\\Local\\Programs\\@opencodedesktop\\OpenCode.exe\"",
    "ватсап": "https://web.whatsapp.com",
    "whatsapp": "https://web.whatsapp.com",
    "вацап": "https://web.whatsapp.com",
}

SITE_PREFIXES = ("http://", "https://", "www.")

MEDIA_KEYS = {
    "play_pause": 0xB3,
    "next": 0xB0,
    "prev": 0xB1,
    "stop": 0xB2,
}

SPECIAL_KEYS = {
    "enter": Key.enter,
    "esc": Key.esc,
    "escape": Key.esc,
    "tab": Key.tab,
    "space": Key.space,
    "backspace": Key.backspace,
    "delete": Key.delete,
    "up": Key.up,
    "down": Key.down,
    "left": Key.left,
    "right": Key.right,
    "home": Key.home,
    "end": Key.end,
    "pageup": Key.page_up,
    "pagedown": Key.page_down,
    "printscreen": Key.print_screen,
    **{f"f{i}": getattr(Key, f"f{i}") for i in range(1, 13)},
}

MODIFIERS = {
    "ctrl": Key.ctrl,
    "control": Key.ctrl,
    "alt": Key.alt,
    "shift": Key.shift,
    "win": Key.cmd,
}


def _vk(code: int) -> None:
    user32 = ctypes.windll.user32
    user32.keybd_event(code, 0, 0, 0)
    user32.keybd_event(code, 0, 2, 0)


class Tools:
    """PC actions available to the model by name."""

    def __init__(
        self,
        config: Config,
        confirm: Callable[[str], bool] | None = None,
        on_event: Callable[[str], None] | None = None,
        lang: str = "ru",
    ) -> None:
        self.config = config
        self.lang = lang
        self.confirm = confirm or (lambda _prompt: False)
        self.on_event = on_event or (lambda _msg: None)
        self.keyboard = KeyboardController()
        self.current_request = ""
        self.audit_path = LOG_DIR / "audit.jsonl"
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)

    def _t(self, ru: str, en: str) -> str:
        """Return the English string."""
        return en

    # ------------------------------------------------------------------ infra
    def _audit(self, tool: str, args: dict[str, Any], status: str, result: str) -> None:
        if not self.config.get("safety.audit_log", True):
            return
        entry = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "tool": tool,
            "args": args,
            "status": status,
            "result": result[:300],
        }
        try:
            with self.audit_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def _ask(self, prompt: str) -> bool:
        self.on_event(f"confirmation: {prompt}")
        return bool(self.confirm(prompt))

    @staticmethod
    def _truncate(text: str, limit: int = 4000) -> str:
        if len(text) <= limit:
            return text
        return text[:limit] + f"\n...truncated ({len(text)} chars)"

    # ------------------------------------------------------------------ schemas
    def schemas(self) -> list[dict[str, Any]]:
        def fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
            return {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                },
            }

        return [
            fn("open_app", "Открыть приложение или сайт по названию.",
               {"name": {"type": "string", "description": "Например: хром, стим, дискорд, ютуб"}}, ["name"]),
            fn("open_url", "Открыть ссылку в браузере.",
               {"url": {"type": "string"}}, ["url"]),
            fn("web_search", "Найти запрос в интернете (откроется браузер).",
               {"query": {"type": "string"}}, ["query"]),
            fn("volume", "Управление громкостью.",
               {"action": {"type": "string", "enum": ["up", "down", "mute", "unmute"]},
                "steps": {"type": "integer", "description": "Сколько шагов по 2%, по умолчанию 3"}}, ["action"]),
            fn("media", "Управление плеером.",
               {"action": {"type": "string", "enum": ["play_pause", "next", "prev", "stop"]}}, ["action"]),
            fn("media_now_playing", "Узнать, что сейчас играет (Spotify / плеер).", {}, []),
            fn("screenshot", "Сделать скриншот всех экранов и вернуть путь к файлу.",
               {}, []),
            fn("type_text", "Напечатать текст в активном окне.",
               {"text": {"type": "string"}}, ["text"]),
            fn("press_keys", "Нажать сочетание клавиш, например 'ctrl+s' или 'alt+tab'.",
               {"combo": {"type": "string"}}, ["combo"]),
            fn("window", "Действия с окнами.",
               {"action": {"type": "string", "enum": ["minimize_all", "show_desktop", "close", "switch", "maximize"]}},
               ["action"]),
            fn("lock_pc", "Заблокировать компьютер.", {}, []),
            fn("close_app", "Закрыть процесс приложения по имени (например: spotify, discord, chrome, steam). Требует подтверждения.",
               {"name": {"type": "string", "description": "Например: spotify, discord, chrome, steam, edge, notepad"}}, ["name"]),
            fn("power", "Выключить, перезагрузить или усыпить ПК. Требует подтверждения.",
               {"action": {"type": "string", "enum": ["sleep", "shutdown", "restart"]}}, ["action"]),
            fn("run_shell", "Выполнить команду PowerShell и вернуть вывод. Требует подтверждения.",
               {"command": {"type": "string"}, "timeout": {"type": "integer"}}, ["command"]),
            fn("read_file", "Прочитать текстовый файл.",
               {"path": {"type": "string"}, "max_chars": {"type": "integer"}}, ["path"]),
            fn("write_file", "Создать или перезаписать файл. Требует подтверждения.",
               {"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]),
            fn("list_dir", "Показать содержимое папки.",
               {"path": {"type": "string"}}, []),
            fn("clipboard", "Прочитать или записать буфер обмена.",
               {"action": {"type": "string", "enum": ["get", "set"]},
                "text": {"type": "string"}}, ["action"]),
            fn("get_time", "Текущие дата и время.", {}, []),
            fn("system_info", "Сведения о системе: CPU, RAM, диск, GPU.", {}, []),
            fn("vocab_add", "Добавить слово в пользовательский словарь распознавания.",
               {"word": {"type": "string", "description": "Слово для добавления"}}, ["word"]),
            fn("vocab_remove", "Удалить слово из пользовательского словаря.",
               {"word": {"type": "string", "description": "Слово для удаления"}}, ["word"]),
            fn("vocab_list", "Показать слова в пользовательском словаре.", {}, []),
            fn("get_weather", "Узнать погоду в городе через интернет (wttr.in).",
               {"city": {"type": "string", "description": "Например: Москва"}}, ["city"]),
        ]

    # ------------------------------------------------------------------ dispatch
    def call(self, name: str, arguments: dict[str, Any]) -> str:
        handler = getattr(self, f"_tool_{name}", None)
        if handler is None:
            return f"Error: unknown tool '{name}'."
        try:
            result = handler(**arguments)
            self._audit(name, arguments, "ok", str(result))
            return result
        except TypeError as exc:
            self._audit(name, arguments, "bad_args", str(exc))
            return f"Bad arguments for {name}: {exc}"
        except Exception as exc:  # noqa: BLE001 - a tool must not crash the loop
            self._audit(name, arguments, "error", f"{type(exc).__name__}: {exc}")
            return f"Error running {name}: {type(exc).__name__}: {exc}"

    # ------------------------------------------------------------------ apps
    def _tool_open_app(self, name: str) -> str:
        key = name.strip().lower().replace("ё", "е")
        target = APP_ALIASES.get(key, name.strip())
        try:
            if target.startswith(SITE_PREFIXES) or re.match(r"^[\w-]+\.[a-z]{2,}(/|$)", target):
                if not target.startswith(SITE_PREFIXES):
                    target = "https://" + target
                webbrowser.open(target)
                return self._t(f"Открыл сайт {target}", f"Opened site {target}")
            if "://" in target or target.endswith(":"):
                os.startfile(target)  # noqa: S606 — протокол приложения
                return self._t(f"Запустил {target}", f"Launched {target}")
            try:
                os.startfile(target)  # noqa: S606 — resolves App Paths on Windows
            except OSError:
                subprocess.Popen(f'start "" {target}', shell=True)  # noqa: S602
            return self._t(f"Запустил {target}", f"Launched {target}")
        except Exception as exc:  # noqa: BLE001
            return self._t(f"Не удалось открыть '{name}': {exc}", f"Failed to open '{name}': {exc}")

    # ------------------------------------------------------------------ close app
    CLOSE_ALIASES = {
        "спотифай": "spotify",
        "spotify": "spotify",
        "дискорд": "discord",
        "discord": "discord",
        "хром": "chrome",
        "chrome": "chrome",
        "браузер": "chrome",
        "browser": "chrome",
        "эдж": "msedge",
        "edge": "msedge",
        "msedge": "msedge",
        "стим": "steam",
        "steam": "steam",
        "телеграм": "telegram",
        "телеграмм": "telegram",
        "telegram": "telegram",
        "блокнот": "notepad",
        "notepad": "notepad",
        "калькулятор": "calc",
        "calc": "calc",
        "calculator": "calc",
        "проводник": "explorer",
        "explorer": "explorer",
        "диспетчер": "taskmgr",
        "taskmgr": "taskmgr",
        "paint": "paint",
        "пэйнт": "paint",
        "рисование": "paint",
        "ножницы": "snipping",
        "snipping": "snipping",
        "эпик": "epic",
        "epic": "epic",
        "epic games": "epic",
        "everything": "everything",
        "все": "everything",
        "всё": "everything",
        "flow launcher": "flow",
        "флоу": "flow",
        "localsend": "localsend",
        "локалсенд": "localsend",
        "quicklook": "quicklook",
        "квиклук": "quicklook",
        "нвидиа": "nvidia",
        "nvidia": "nvidia",
        "nvidia app": "nvidia",
        "олама": "ollama",
        "ollama": "ollama",
        "валорант": "valorant",
        "valorant": "valorant",
        "рает": "riot",
        "раёт": "riot",
        "riot": "riot",
        "riot client": "riot",
        "осу": "osu",
        "osu": "osu",
        "роблокс": "roblox",
        "roblox": "roblox",
        "ютуб мьюзик": "ytmdesktop",
        "youtube music": "ytmdesktop",
        "ардуино": "arduino",
        "arduino": "arduino",
        "опенкод": "opencode",
        "opencode": "opencode",
        "cmd": "cmd",
        "командная строка": "cmd",
        "реестр": "regedit",
        "regedit": "regedit",
        "панель управления": "control",
        "control panel": "control",
    }

    # Процессы, которые можно закрывать (защита от случайного закрытия системы).
    CLOSE_ALLOWED = {
        "spotify": "Spotify.exe",
        "discord": "Discord.exe",
        "chrome": "chrome.exe",
        "msedge": "msedge.exe",
        "steam": "Steam.exe",
        "telegram": "Telegram.exe",
        "notepad": "notepad.exe",
        "calc": "calc.exe",
        "explorer": "explorer.exe",
        "taskmgr": "taskmgr.exe",
        "paint": "mspaint.exe",
        "snipping": "SnippingTool.exe",
        "epic": "EpicGamesLauncher.exe",
        "everything": "Everything.exe",
        "flow": "Flow.Launcher.exe",
        "localsend": "localsend_app.exe",
        "quicklook": "QuickLook.exe",
        "nvidia": "NVIDIA App.exe",
        "ollama": "ollama app.exe",
        "valorant": "VALORANT.exe",
        "riot": "RiotClientServices.exe",
        "osu": "osu!.exe",
        "roblox": "RobloxPlayerBeta.exe",
        "ytmdesktop": "ytmdesktop.exe",
        "arduino": "Arduino IDE.exe",
        "opencode": "OpenCode.exe",
        "cmd": "cmd.exe",
        "regedit": "regedit.exe",
        "control": "control.exe",
    }

    def _tool_close_app(self, name: str) -> str:
        key = name.strip().lower().replace("ё", "е")
        key = self.CLOSE_ALIASES.get(key, key)
        exe = self.CLOSE_ALLOWED.get(key)
        if exe is None:
            return self._t(
                f"Не знаю процесс «{name}». Назови приложение по имени, например Spotify, Discord, Хром.",
                f"Don't know process «{name}». Name an app, e.g. Spotify, Discord, Chrome.",
            )
        ru_prompt = f"Закрыть «{name}»?"
        en_prompt = f"Close «{name}»?"
        if not self._ask(self._t(ru_prompt, en_prompt)):
            return self._t("Пользователь отменил закрытие.", "User cancelled closing.")
        try:
            completed = subprocess.run(
                ["taskkill", "/IM", exe, "/F"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
            )
            if completed.returncode == 0:
                return self._t(f"Закрыл «{name}»", f"Closed «{name}»")
            output = (completed.stdout or completed.stderr or "").strip()
            return self._t(
                f"Не удалось закрыть «{name}»: {output}",
                f"Could not close «{name}»: {output}",
            )
        except Exception as exc:  # noqa: BLE001
            return self._t(
                f"Ошибка при закрытии «{name}»: {type(exc).__name__}: {exc}",
                f"Error closing «{name}»: {type(exc).__name__}: {exc}",
            )

    def _tool_open_url(self, url: str) -> str:
        if not url.startswith(SITE_PREFIXES):
            url = "https://" + url
        webbrowser.open(url)
        return self._t(f"Открыл {url}", f"Opened {url}")

    def _tool_web_search(self, query: str) -> str:
        from urllib.parse import quote_plus

        webbrowser.open(f"https://www.google.com/search?q={quote_plus(query)}")
        webbrowser.open(f"https://www.google.com/search?q={quote_plus(query)}")
        return self._t(
            "Открыл поиск в браузере. Прочитать результаты я не могу — предложи пользователю посмотреть.",
            "Opened search in the browser. I can't read the results — suggest the user have a look.",
        )

    # ------------------------------------------------------------------ weather
    def _tool_get_weather(self, city: str = "Москва") -> str:
        """Погода через wttr.in (бесплатно, без ключа)."""
        try:
            wind_label = "ветер" if self.lang == "ru" else "wind"
            url = (
                f"https://wttr.in/{quote(city)}?"
                f"format=%l:+%t,+%C,+{wind_label}+%w&lang={self.lang}"
            )
            response = requests.get(url, headers={"User-Agent": "curl"}, timeout=10)
            if response.status_code != 200:
                return self._t(f"Не удалось узнать погоду для «{city}».", f"Could not get weather for «{city}».")
            text = response.text.strip()
            if not text:
                return self._t(f"Не удалось узнать погоду для «{city}».", f"Could not get weather for «{city}».")
            return text
        except Exception as exc:  # noqa: BLE001
            return self._t(f"Ошибка погоды: {type(exc).__name__}: {exc}", f"Weather error: {type(exc).__name__}: {exc}")

    # ------------------------------------------------------------------ sound
    def _tool_volume(self, action: str, steps: int = 3) -> str:
        mapping = {"up": 0xAF, "down": 0xAE}
        if action in mapping:
            for _ in range(max(1, min(int(steps), 25))):
                _vk(mapping[action])
                time.sleep(0.03)
            return self._t("Громкость выше", "Volume up") if action == "up" else self._t("Громкость ниже", "Volume down")
        if action in {"mute", "unmute"}:
            _vk(0xAD)
            return self._t("Переключил звук", "Sound toggled")
        return self._t(f"Неизвестное действие громкости: {action}", f"Unknown volume action: {action}")

    def _tool_media(self, action: str) -> str:
        code = MEDIA_KEYS.get(action)
        if code is None:
            return self._t(f"Неизвестное действие плеера: {action}", f"Unknown media action: {action}")
        _vk(code)
        return {
            "play_pause": self._t("Пауза/воспроизведение", "Pause/play"),
            "next": self._t("Следующий трек", "Next track"),
            "prev": self._t("Предыдущий трек", "Previous track"),
            "stop": self._t("Стоп", "Stop"),
        }[action]

    def _tool_screenshot(self) -> str:
        target = Path.home() / "Pictures" / "Jarvis"
        target.mkdir(parents=True, exist_ok=True)
        path = target / f"shot_{datetime.now():%Y%m%d_%H%M%S}.png"
        script = (
            "Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
            "$b=[System.Windows.Forms.SystemInformation]::VirtualScreen;"
            "$bmp=New-Object System.Drawing.Bitmap $b.Width,$b.Height;"
            "$g=[System.Drawing.Graphics]::FromImage($bmp);"
            "try { $g.CopyFromScreen($b.Left,$b.Top,0,0,$bmp.Size); "
            f"$bmp.Save('{path}',[System.Drawing.Imaging.ImageFormat]::Png); "
            "$ok=$true } catch { $ok=$false }; "
            "$bmp.Dispose();$g.Dispose(); "
            "if ($ok) { Write-Output 'ok' } else { Write-Output 'fail' }"
        )
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        )
        output = (completed.stdout or "").strip()
        if output == "ok" and path.exists():
            return self._t(f"Скриншот сохранён: {path}", f"Screenshot saved: {path}")
        return self._t(
            "Не удалось сделать скриншот. Возможно, экран заблокирован.",
            "Could not take a screenshot. The screen may be locked.",
        )

    def _tool_media_now_playing(self) -> str:
        """Пытается определить текущий трек через Windows Media Session API."""
        script = (
            "Add-Type -AssemblyName System.Runtime.WindowsRuntime 2>$null; "
            "$null"
        )
        # Try PowerShell Get-MediaSession if available (Windows 11)
        script = (
            "try { "
            "$s = Get-MediaSession 2>$null; "
            "if ($s) { $s | Select-Object -First 1 Title, Artist, Album | Format-List | Out-String } "
            "else { 'none' } "
            "} catch { 'none' }"
        )
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
        )
        output = (completed.stdout or "").strip()
        if output and output != "none" and "Title" in output:
            return self._t(f"Сейчас играет: {output}", f"Now playing: {output}")
        # Fallback: check Spotify process
        try:
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-Process spotify -ErrorAction SilentlyContinue | Select-Object -First 1 | Out-Null; "
                 "if ($?) { 'running' } else { 'not_running' }"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
            )
            result = (completed.stdout or "").strip()
            if result == "running":
                return self._t("Spotify запущен", "Spotify is running")
            return self._t("Spotify не запущен", "Spotify is not running")
        except Exception:  # noqa: BLE001
            pass
        return self._t("Не удалось определить текущий трек.", "Could not determine the current track.")
        target.mkdir(parents=True, exist_ok=True)
        path = target / f"shot_{datetime.now():%Y%m%d_%H%M%S}.png"
        script = (
            "Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
            "$b=[System.Windows.Forms.SystemInformation]::VirtualScreen;"
            "$bmp=New-Object System.Drawing.Bitmap $b.Width,$b.Height;"
            "$g=[System.Drawing.Graphics]::FromImage($bmp);"
            "$g.CopyFromScreen($b.Left,$b.Top,0,0,$bmp.Size);"
            f"$bmp.Save('{path}',[System.Drawing.Imaging.ImageFormat]::Png);"
            "$bmp.Dispose();$g.Dispose()"
        )
        subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True, timeout=30)
        return self._t(f"Скриншот сохранён: {path}", f"Screenshot saved: {path}")

    def _tool_type_text(self, text: str) -> str:
        request = getattr(self, "current_request", "") or ""
        if request and not re.search(
            r"напечат|введ|напиш|вставь|набери|type|введи|print|type|write|enter", request, re.IGNORECASE
        ):
            return self._t(
                "Отказано: пользователь не просил печатать текст в активном окне. Просто ответь голосом.",
                "Denied: the user didn't ask to type text in the active window. Just answer by voice.",
            )
        time.sleep(0.15)
        self.keyboard.type(text)
        return self._t(f"Напечатал {len(text)} символов", f"Typed {len(text)} characters")

    def _tool_press_keys(self, combo: str) -> str:
        parts = [part.strip().lower() for part in combo.replace(" ", "").split("+") if part.strip()]
        if not parts:
            return self._t("Пустое сочетание клавиш", "Empty key combination")
        modifiers = [MODIFIERS[p] for p in parts[:-1] if p in MODIFIERS]
        last = parts[-1]
        key = SPECIAL_KEYS.get(last, last if len(last) == 1 else None)
        if key is None:
            return f"Неизвестная клавиша: {last}"
        for modifier in modifiers:
            self.keyboard.press(modifier)
        try:
            self.keyboard.press(key)
            self.keyboard.release(key)
        finally:
            for modifier in reversed(modifiers):
                self.keyboard.release(modifier)
        return f"Нажал {combo}"

    def _tool_window(self, action: str) -> str:
        actions = {
            "minimize_all": "win+d",
            "show_desktop": "win+d",
            "close": "alt+f4",
            "switch": "alt+tab",
            "maximize": "win+up",
        }
        combo = actions.get(action)
        if combo is None:
            return self._t(f"Неизвестное действие с окном: {action}", f"Unknown window action: {action}")
        return self._tool_press_keys(combo)

    # ------------------------------------------------------------------ power
    def _tool_lock_pc(self) -> str:
        ctypes.windll.user32.LockWorkStation()
        return self._t("Компьютер заблокирован", "Computer locked")

    def _tool_power(self, action: str) -> str:
        ru_prompt = f"Выполнить «{action}» для компьютера?"
        en_prompt = f"Perform «{action}» on the computer?"
        if not self._ask(self._t(ru_prompt, en_prompt)):
            return self._t("Пользователь отменил действие.", "User cancelled the action.")
        if action == "sleep":
            subprocess.run(
                ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
                check=False,
            )
            return self._t("Усыпляю компьютер", "Putting the computer to sleep")
        if action == "shutdown":
            subprocess.run(["shutdown", "/s", "/t", "5"], check=False)
            return self._t("Выключаю компьютер через 5 секунд", "Shutting down the computer in 5 seconds")
        if action == "restart":
            subprocess.run(["shutdown", "/r", "/t", "5"], check=False)
            return self._t("Перезагружаю компьютер через 5 секунд", "Restarting the computer in 5 seconds")
        return self._t(f"Неизвестное действие питания: {action}", f"Unknown power action: {action}")

    # ------------------------------------------------------------------ shell
    def _tool_run_shell(self, command: str, timeout: int = 60) -> str:
        lowered = command.lower()
        for pattern in FORBIDDEN_PATTERNS:
            if re.search(pattern, lowered):
                self._audit("run_shell", {"command": command}, "blocked", "forbidden pattern")
                return (
                    self._t("Отказано: команда похожа на разрушительную для системы. ", "Denied: the command looks destructive for the system. ")
                    + self._t("Выполни её вручную, если действительно нужно.", "Run it manually if you really need to.")
                )
        if not SAFE_SHELL.search(command):
            ru_prompt = f"Выполнить команду: {command[:120]}?"
            en_prompt = f"Run command: {command[:120]}?"
            if not self._ask(self._t(ru_prompt, en_prompt)):
                return self._t("Пользователь отменил команду.", "User cancelled the command.")
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(5, min(int(timeout), 300)),
        )
        output = (completed.stdout or "").strip()
        error = (completed.stderr or "").strip()
        if completed.returncode != 0 and error:
            return self._truncate(self._t(f"Код {completed.returncode}. Ошибка: {error}", f"Code {completed.returncode}. Error: {error}"))
        return self._truncate(output or self._t("Команда выполнена без вывода.", "Command executed without output."))

    # ------------------------------------------------------------------ files
    def _tool_read_file(self, path: str, max_chars: int = 4000) -> str:
        file = Path(os.path.expandvars(os.path.expanduser(path)))
        if not file.is_file():
            return self._t(f"Файл не найден: {file}", f"File not found: {file}")
        try:
            return self._truncate(file.read_text(encoding="utf-8", errors="replace"), max_chars)
        except OSError as exc:
            return self._t(f"Не смог прочитать: {exc}", f"Could not read: {exc}")

    def _tool_write_file(self, path: str, content: str) -> str:
        file = Path(os.path.expandvars(os.path.expanduser(path)))
        if not self._ask(self._t(f"Записать файл {file}?", f"Write file {file}?")):
            return self._t("Пользователь отменил запись.", "User cancelled writing.")
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content, encoding="utf-8")
        return self._t(f"Записал {file} ({len(content)} символов)", f"Wrote {file} ({len(content)} characters)")

    def _tool_list_dir(self, path: str = ".") -> str:
        folder = Path(os.path.expandvars(os.path.expanduser(path)))
        if not folder.is_dir():
            return self._t(f"Папка не найдена: {folder}", f"Folder not found: {folder}")
        lines = []
        for entry in sorted(folder.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))[:60]:
            size = f"{entry.stat().st_size:>10,}" if entry.is_file() else "     <dir>"
            lines.append(f"{size}  {entry.name}")
        return self._truncate("\n".join(lines) or self._t("Папка пуста.", "Folder is empty."))

    # ------------------------------------------------------------------ misc
    def _tool_clipboard(self, action: str, text: str = "") -> str:
        if action == "get":
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=15,
            )
            return self._truncate((completed.stdout or "").strip() or self._t("Буфер пуст.", "Clipboard is empty."))
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", "$input | Set-Clipboard"],
            input=text,
            text=True,
            encoding="utf-8",
            timeout=15,
        )
        return self._t(f"Скопировал в буфер ({len(text)} символов)", f"Copied to clipboard ({len(text)} characters)")

    def _tool_get_time(self) -> str:
        if self.lang == "en":
            return datetime.now().strftime("%H:%M, %d %B %Y")
        months = (
            "января", "февраля", "марта", "апреля", "мая", "июня",
            "июля", "августа", "сентября", "октября", "ноября", "декабря",
        )
        now = datetime.now()
        return f"{now:%H:%M}, {now.day} {months[now.month - 1]} {now.year} года"

    def _tool_system_info(self) -> str:
        disk_label = "диск C: свободно {free} из {total} GB" if self.lang == "ru" else "C: drive free {free} of {total} GB"
        script = (
            "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; "
            "$c=Get-CimInstance Win32_Processor|Select-Object -First 1;"
            "$m=[math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory/1GB,1);"
            "$g=(Get-CimInstance Win32_VideoController|Select-Object -First 1).Name;"
            "$d=Get-PSDrive C;"
            f"\"CPU: $($c.Name); RAM: $m GB; GPU: $g; " +
            disk_label.replace("{free}", "$([math]::Round($d.Free/1GB,1))").replace("{total}", "$([math]::Round(($d.Used+$d.Free)/1GB,1))") + "\""
        )
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        return self._truncate((completed.stdout or completed.stderr or "").strip())

    def _tool_vocab_add(self, word: str) -> str:
        vocab = getattr(self, "vocab", None)
        if vocab is not None:
            result = vocab.add_word(word)
            if result:
                return self._t(f"Запомнил слово «{word}».", f"Remembered word «{word}».")
            return self._t(f"Слово «{word}» уже в словаре.", f"Word «{word}» is already in vocabulary.")
        return self._t("Словарь не доступен.", "Vocabulary not available.")

    def _tool_vocab_remove(self, word: str) -> str:
        vocab = getattr(self, "vocab", None)
        if vocab is not None:
            result = vocab.remove_word(word)
            if result:
                return self._t(f"Удалил слово «{word}» из словаря.", f"Removed word «{word}» from vocabulary.")
            return self._t(f"Слова «{word}» нет в словаре.", f"Word «{word}» is not in vocabulary.")
        return self._t("Словарь не доступен.", "Vocabulary not available.")

    def _tool_vocab_list(self) -> str:
        vocab = getattr(self, "vocab", None)
        if vocab is not None:
            words = vocab.list_words()
            return self._t(
                f"В словаре {len(words)} слов: {', '.join(words[:20])}{'...' if len(words) > 20 else ''}.",
                f"Vocabulary has {len(words)} words: {', '.join(words[:20])}{'...' if len(words) > 20 else ''}.",
            )
        return self._t("Словарь не доступен.", "Vocabulary not available.")
