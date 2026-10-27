"""Entry point: voice loop, confirmations, and CLI commands."""

from __future__ import annotations

import argparse
import ctypes
import difflib
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .asr import Transcriber
from .audio import Mic, list_input_devices
from .config import LOG_DIR, Config
from .llm import LLM
from .local_commands import LocalCommands, Result, normalize
from .tools import Tools
from .tts import Speaker
from .vocab import Vocabulary

BANNER = r"""
     ██╗ █████╗ ██████╗ ██╗   ██╗██╗███████╗
     ██║██╔══██╗██╔══██╗██║   ██║██║██╔════╝
     ██║███████║██████╔╝██║   ██║██║███████╗
██   ██║██╔══██║██╔══██╗╚██╗ ██╔╝██║╚════██║
╚█████╔╝██║  ██║██║  ██║ ╚████╔╝ ██║███████║
 ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚═╝╚══════╝
"""

YES_WORDS = {"да", "ага", "угу", "подтверждаю", "выполняй", "конечно", "давай", "ок", "окей", "yes"}
NO_WORDS = {"нет", "не", "отмена", "отмени", "стоп", "no", "неа"}


# Suppress torch/onnx warnings
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")


def init_console() -> None:
    """Enables ANSI colors and UTF-8 in the Windows console."""
    try:
        for stream in (sys.stdout, sys.stderr):
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        pass
    try:
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
        # force UTF-8 code page
        kernel32.SetConsoleCP(65001)
        kernel32.SetConsoleOutputCP(65001)
    except Exception:  # noqa: BLE001
        pass


def paint(text: str, color: str) -> str:
    codes = {
        "dim": "90",
        "cyan": "36",
        "green": "32",
        "yellow": "33",
        "red": "31",
        "magenta": "35",
        "bold": "1",
    }
    return f"\033[{codes.get(color, '0')}m{text}\033[0m"


class Assistant:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.config = Config()
        self._apply_args()
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.log_path = LOG_DIR / "jarvis.log"

        audio_cfg = self.config.section("audio")
        self.mic = Mic(
            sample_rate=int(audio_cfg.get("sample_rate", 16000)),
            device=self._resolve_device(audio_cfg.get("device")),
            silence_ms=int(audio_cfg.get("silence_ms", 700)),
            max_phrase_s=float(audio_cfg.get("max_phrase_s", 20)),
            min_rms=float(audio_cfg.get("min_rms", 220)),
            pre_roll_ms=int(audio_cfg.get("pre_roll_ms", 300)),
        )

        asr_cfg = self.config.section("asr")
        self.asr = Transcriber(
            model_name=str(asr_cfg.get("model", "small")),
            device=str(asr_cfg.get("device", "auto")),
            compute_type=str(asr_cfg.get("compute_type", "auto")),
            language=asr_cfg.get("language", "ru"),
            beam_size=int(asr_cfg.get("beam_size", 1)),
        )
        self.vocab = Vocabulary(
            LOG_DIR / "vocab.json",
            enabled=bool(asr_cfg.get("learn_words", True)),
            limit=int(asr_cfg.get("hotwords_limit", 40)),
            min_count=int(asr_cfg.get("hotwords_min_count", 2)),
            seed_words=[str(w) for w in asr_cfg.get("hotwords") or []] + [
                "firefox", "chrome", "discord", "steam", "spotify", "telegram",
                "notepad", "калькулятор", "терминал", "everything", "epic",
                "valorant", "osu", "roblox", "youtube", "arduino", "opencode",
                "localsend", "quicklook", "ollama", "nvidia", "paint",
            ],
            exclude_words={normalize(str(w)) for w in self.config.get("wake_words") or []},
        )

        tts_cfg = self.config.section("tts")
        self.speaker = Speaker(
            enabled=bool(tts_cfg.get("enabled", True)) and not args.no_tts,
            voice=str(tts_cfg.get("voice", "ru-RU-SvetlanaNeural")),
            rate=str(tts_cfg.get("rate", "+12%")),
            pitch=str(tts_cfg.get("pitch", "+120Hz")),
            volume=str(tts_cfg.get("volume", "+0%")),
            cache_dir=LOG_DIR / "tts_cache",
        )

        self.tools = Tools(
            config=self.config,
            confirm=self._confirm,
            on_event=lambda msg: self.print_status(msg, "yellow"),
        )
        self.tools.vocab = self.vocab
        self.asr.hotwords = self.vocab.hotwords()
        self.local = LocalCommands(self.tools)
        self.llm = LLM(self.config, self.tools)
        self._stop = threading.Event()
        self._busy = False
        self._conversation_until: float = 0.0
        self._conversation_timeout: float = float(audio_cfg.get("conversation_timeout", 8.0))
        self._conversation_mode: bool = bool(audio_cfg.get("continuous_conversation", False))
        self._pgup_activated = threading.Event()
        self._pgup_listener = None
        self._pgup_activated = threading.Event()

    # ------------------------------------------------------------------ setup
    def _apply_args(self) -> None:
        if self.args.model:
            self.config.set("llm.model", self.args.model)
        if self.args.asr_model:
            self.config.set("asr.model", self.args.asr_model)
        if self.args.device is not None:
            self.config.set("audio.device", self.args.device)
        if self.args.no_wake:
            self.config.set("require_wake_word", False)

    def _resolve_device(self, value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, int):
            return value
        needle = str(value).lower()
        for item in list_input_devices():
            if needle in item["name"].lower():
                return int(item["index"])
        return None

    # ------------------------------------------------------------------ output
    def log(self, kind: str, text: str) -> None:
        try:
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}\t{kind}\t{text}\n")
        except OSError:
            pass

    def print_status(self, text: str, color: str = "dim") -> None:
        print(paint(f"  · {text}", color), flush=True)

    def say(self, text: str, lang: str | None = None) -> None:
        print(paint(f"🔊 {text}", "green"), flush=True)
        self.log("assistant", text)
        self.speaker.say(text, lang=lang)

    # ------------------------------------------------------------------ confirm
    def _confirm(self, prompt: str) -> bool:
        """Asks for voice confirmation and listens for the answer."""
        ru_prompt = prompt
        en_prompt = prompt  # prompt is already set by caller with _t()
        print(paint(f"🔊 {prompt}", "green"), flush=True)
        self.log("assistant", prompt)
        self.speaker.say(f"{prompt} Say yes or no.", lang=self.tools.lang, blocking=True)
        time.sleep(0.25)
        self.print_status("waiting for 'yes' or 'no' (8 seconds)", "yellow")
        self._busy = True
        try:
            audio = self.mic.record_phrase(wait_timeout=8)
        finally:
            self._busy = False
        if audio is None:
            self.print_status("didn't hear an answer - cancelling", "red")
            return False
        answer = normalize(self.asr.transcribe(audio, hotwords=self.vocab.hotwords()))
        self.vocab.learn(answer)
        print(paint(f"  ↳ {answer}", "cyan"), flush=True)
        tokens = set(answer.split())
        if tokens & NO_WORDS:
            return False
        return bool(tokens & YES_WORDS) or "подтвержда" in answer or "confirm" in answer

    # ------------------------------------------------------------------ pipeline
    def handle_text(self, text: str) -> bool:
        """Processes a phrase. Returns True if the program should exit."""
        phrase = normalize(text)
        if not phrase:
            return False
        self.log("user", phrase)
        lang = "ru" if re.search(r"[а-яё]", phrase) else "en"
        self.tools.lang = "en"
        self.local.lang = lang
        self.speaker.lang = "en"

        stripped, has_wake = self._strip_wake(phrase)
        require_wake = bool(self.config.get("require_wake_word", True))
        in_conversation = time.monotonic() < self._conversation_until
        if require_wake and not has_wake and not in_conversation:
            self.print_status(f"ignored: {phrase}", "dim")
            return False

        command = stripped if has_wake else phrase
        if not command:
            # Called by name without a command - short response, stay connected.
            self._conversation_until = time.monotonic() + self._conversation_timeout
            self.say("I'm listening.", lang=lang)
            return False

        # После команды по умолчанию прослушивание останавливается (авто-стоп).
        # Непрерывный диалог — только если включён в конфиге.
        if self._conversation_mode:
            self._conversation_until = time.monotonic() + self._conversation_timeout

        self._busy = True
        self.tools.current_request = command
        try:
            local_result: Result | None = self.local.handle(command)
            if local_result is not None:
                self.print_status(f"local: {command}", "cyan")
                # Учимся только если команда выполнилась успешно
                if local_result.text and not any(
                    ind in local_result.text.lower() for ind in ("error", "cancelled", "not found", "failed")
                ):
                    self.vocab.learn(phrase, success=True)
                    self.asr.hotwords = self.vocab.hotwords()
                self.say(local_result.text)
                return local_result.exit

            self.print_status(f"thinking: {command}", "magenta")
            started = time.monotonic()
            answer = self.llm.chat(command, on_tool=self._on_tool)
            elapsed = time.monotonic() - started
            self.print_status(f"answered in {elapsed:.1f} s", "dim")
            # Учимся из успешного ответа LLM
            self.vocab.learn(phrase, success=True)
            self.asr.hotwords = self.vocab.hotwords()
            self.say(answer)
            return False
        finally:
            self._busy = False
            self.tools.current_request = ""
            self.speaker.wait()

    def _on_tool(self, name: str, arguments: dict[str, Any]) -> None:
        pretty = ", ".join(f"{k}={v}" for k, v in arguments.items())
        self.print_status(f"tool: {name}({pretty})", "yellow")
        self.log("tool", f"{name} {arguments}")

    def _strip_wake(self, phrase: str) -> tuple[str, bool]:
        """Looks for the wake word, tolerant to recognition errors."""
        words = phrase.split()
        for word in self.config.get("wake_words", []):
            needle = normalize(str(word))
            if not needle:
                continue
            if " " not in needle and needle in phrase:
                return phrase.replace(needle, " ", 1).strip(), True
            if " " in needle and needle in phrase:
                return phrase.replace(needle, " ", 1).strip(), True
            for index, token in enumerate(words):
                # "shutdown" is close to "shadow" in edit distance; never
                # strip a power command as if it were the wake word.
                if needle == "shadow" and token in {"shutdown", "shutting"}:
                    continue
                # Lower threshold for shadow because Whisper often misrecognizes it.
                threshold = 0.6 if needle in ("shadow", "шедоу", "шэдоу", "шадоу") else 0.8
                if difflib.SequenceMatcher(None, token, needle).ratio() >= threshold:
                    rest = words[:index] + words[index + 1 :]
                    return " ".join(rest), True
        return phrase, False

    def _warmup_audio(self) -> None:
        """Kick the ASR model and VAD with a short silent sample so the first real
        phrase is not delayed after PgUp (cold-start latency)."""
        try:
            import numpy as np

            silent = np.zeros(1600, dtype=np.int16)
            self.asr.transcribe(silent)
            try:
                self.mic._has_speech(silent)
            except Exception:
                pass
        except Exception:  # noqa: BLE001 - warmup must not break startup
            pass

    # ------------------------------------------------------------------ modes
    # ------------------------------------------------------------------ modes
    def check(self) -> int:
        print(paint("Environment check", "bold"))
        ok = True

        devices = list_input_devices()
        if devices:
            default = next((d for d in devices if d["default"]), devices[0])
            self.print_status(f"microphone: {default['name']} (idx {default['index']})", "green")
        else:
            self.print_status("microphone not found", "red")
            ok = False

        if self.llm.available():
            models = self.llm.models()
            self.print_status(f"Ollama: running, {len(models)} models", "green")
            if self.llm.has_model():
                self.print_status(f"model: {self.llm.model}", "green")
            else:
                self.print_status(f"model {self.llm.model} not downloaded", "red")
                ok = False
        else:
            self.print_status("Ollama unavailable (start it from the tray)", "red")
            ok = False

        self.print_status("loading speech model...", "dim")
        try:
            self.asr.load()
            self.print_status(f"speech recognition: {self.asr.model_name}", "green")
        except Exception as exc:  # noqa: BLE001
            self.print_status(f"speech recognition failed: {exc}", "red")
            ok = False

        return 0 if ok else 1

    def run_once(self, text: str) -> int:
        text = self.vocab.correct(text)
        self.handle_text(text)
        self.speaker.shutdown()
        return 0

    def calibrate(self, seconds: float = 4.0) -> int:
        self.mic.open()
        self.print_status("measuring background noise...", "dim")
        floor = self.mic.calibrate()
        self.print_status(f"noise {floor:.0f}, threshold {self.mic.threshold:.0f}", "cyan")
        self.print_status("say something (to check the level)", "dim")
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            audio = self.mic.record_phrase(wait_timeout=1)
            if audio is None:
                continue
            peak = float(abs(audio).max())
            self.print_status(f"phrase {len(audio) / 16000:.1f} s, peak {peak:.0f}", "green")
        self.mic.close()
        return 0

    def run(self) -> int:
        print(paint(BANNER, "cyan"))
        print(paint(f"  {self.config.get('assistant_name')} - local model "
                    f"{self.config.get('llm.model')} - whisper {self.config.get('asr.model')}", "dim"))
        print(paint("  PgUp - activate. Or speak directly. 'shut down' / 'exit' - quit.\n", "dim"))

        self.mic.open()
        self.print_status("calibrating microphone...", "dim")
        floor = self.mic.calibrate()
        self.print_status(f"noise {floor:.0f}, threshold {self.mic.threshold:.0f}", "dim")
        self.asr.load()
        threading.Thread(target=self._warmup_audio, daemon=True).start()
        hot = self.vocab.hotwords()
        if hot:
            self.print_status(f"feeding recognizer {len(hot.split())} frequent words", "dim")
        threading.Thread(target=self.llm.warmup, daemon=True).start()
        self.print_status("warming up the neural network...", "dim")
        self.print_status("ready. Listening to microphone.", "green")

        # Активация по PgUp (через pynput keyboard.Listener)
        self._pgup_activated = threading.Event()
        self._pgup_listener = None
        try:
            from pynput import keyboard

            def on_pgup(key):
                if key == keyboard.Key.page_up:
                    self._pgup_activated.set()

            self._pgup_listener = keyboard.Listener(on_press=on_pgup)
            self._pgup_listener.start()
        except Exception:  # noqa: BLE001
            self._pgup_listener = None

        try:
            while not self._stop.is_set():
                try:
                    in_conversation = time.monotonic() < self._conversation_until
                    # If not in conversation - wait for PgUp or wake word.
                    if not in_conversation:
                        self.print_status("waiting for PgUp or wake word...", "dim")
                        # Ждём PgUp или wake word
                        while not self._stop.is_set():
                            if self._pgup_activated.is_set():
                                self._pgup_activated.clear()
                                break
                            if self.config.get("wake_word_enabled", False):
                                detected = self.mic.wait_for_wake_word(timeout=0.5)
                                if detected:
                                    break
                            time.sleep(0.1)
                        if self._stop.is_set():
                            break
                        self.print_status("listening...", "green")
                        time.sleep(0.2)

                    wait = None if not in_conversation else self._conversation_timeout
                    audio = self.mic.record_phrase(wait_timeout=wait)
                    if audio is None or self._stop.is_set():
                        if in_conversation:
                            self._conversation_until = 0.0
                            self.print_status("conversation mode ended", "dim")
                        continue
                    heard = self.asr.transcribe(audio, hotwords=self.vocab.hotwords())
                    # Применяем исправления из словаря (ASR ошибки → правильные слова)
                    heard = self.vocab.correct(heard)
                    if not heard:
                        continue
                    print(paint(f"🎤 {heard}", "cyan"), flush=True)
                    if self.handle_text(heard):
                        break
                except Exception as exc:  # noqa: BLE001 — одна фраза не должна убить ассистента
                    self.print_status(f"phrase error: {type(exc).__name__}: {exc}", "red")
                    self.log("error", f"phrase: {type(exc).__name__}: {exc}")
        except KeyboardInterrupt:
            print()
        finally:
            self.print_status("stopping...", "dim")
            if self._pgup_listener is not None:
                self._pgup_listener.stop()
            self.mic.close()
            self.speaker.shutdown()
            self._stop.set()
        return 0


def autostart_shortcut(enable: bool) -> int:
    """Adds or removes the assistant from Windows startup."""
    startup = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup"
    shortcut = startup / "Jarvis.lnk"
    if not enable:
        if shortcut.exists():
            shortcut.unlink()
            print(paint(f"removed: {shortcut}", "green"))
        else:
            print(paint("autostart already disabled", "dim"))
        return 0

    target = Path(__file__).resolve().parent.parent / "jarvis.bat"
    script = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%s');"
        "$s.TargetPath='%s';$s.WorkingDirectory='%s';$s.Save()"
    ) % (shortcut, target, target.parent)
    subprocess.run(["powershell", "-NoProfile", "-Command", script], check=False)
    if shortcut.exists():
        print(paint(f"enabled: {shortcut}", "green"))
        return 0
    print(paint("failed to create shortcut", "red"))
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jarvis", description="Voice assistant with a local neural network."
    )
    parser.add_argument("--text", help="process a text command without microphone")
    parser.add_argument("--once", action="store_true", help="exit after one command")
    parser.add_argument("--check", action="store_true", help="check the environment and exit")
    parser.add_argument("--calibrate", action="store_true", help="check microphone and signal level")
    parser.add_argument("--list-devices", action="store_true", help="show input devices")
    parser.add_argument("--device", help="microphone index or name part")
    parser.add_argument("--model", help="Ollama model, e.g. qwen3:8b")
    parser.add_argument("--asr-model", help="whisper model: tiny/base/small/medium")
    parser.add_argument("--no-tts", action="store_true", help="disable voice output")
    parser.add_argument("--no-wake", action="store_true", help="listen without wake word")
    parser.add_argument("--autostart", action="store_true", help="add to Windows startup")
    parser.add_argument("--no-autostart", action="store_true", help="remove from startup")
    parser.add_argument("--vocab", action="store_true", help="show learned hint words")
    parser.add_argument("--remember", action="append", metavar="WORD",
                        help="word to always recognize (can be repeated)")
    parser.add_argument("--forget", action="append", metavar="WORD",
                        help="forget a word from the vocabulary (can be repeated)")
    return parser


def manage_vocab(args: argparse.Namespace) -> int:
    """View and edit the frequent-word vocabulary without running the assistant."""
    config = Config()
    asr_cfg = config.section("asr")
    vocab = Vocabulary(
        LOG_DIR / "vocab.json",
        seed_words=[str(w) for w in asr_cfg.get("hotwords") or []],
    )
    for word in args.remember or []:
        if vocab.add_word(word):
            print(paint(f"remembered: {word}", "green"))
        else:
            print(paint(f"already in vocabulary: {word}", "dim"))
    for word in args.forget or []:
        if vocab.remove_word(word):
            print(paint(f"forgot: {word}", "green"))
        else:
            print(paint(f"not in vocabulary: {word}", "dim"))
    if args.vocab:
        words = vocab.list_words()
        if words:
            print(paint("vocabulary: " + ", ".join(words[:40]), "cyan"))
        stats = vocab.stats()
        learned = stats.get("learned", {})
        if learned:
            print(paint("learned (word x count):", "bold"))
            for word, count in learned.items():
                print(f"  {word} ×{count}")
        if not words and not learned:
            print(paint("vocabulary is empty - assistant has not learned anything yet.", "dim"))
    return 0


def main(argv: list[str] | None = None) -> int:
    init_console()
    args = build_parser().parse_args(argv)

    if args.list_devices:
        for device in list_input_devices():
            mark = "*" if device["default"] else " "
            print(f"{mark} [{device['index']}] {device['name']}")
        return 0

    if args.device is not None and str(args.device).isdigit():
        args.device = int(args.device)

    if args.autostart:
        return autostart_shortcut(True)
    if args.no_autostart:
        return autostart_shortcut(False)
    if args.vocab or args.remember or args.forget:
        return manage_vocab(args)

    assistant = Assistant(args)
    if args.check:
        return assistant.check()
    if args.calibrate:
        return assistant.calibrate()
    if args.text:
        return assistant.run_once(args.text)
    return assistant.run()


if __name__ == "__main__":
    sys.exit(main())
