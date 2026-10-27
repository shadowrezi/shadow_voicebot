"""Voice output: Edge TTS neural voice, offline fallback to SAPI."""

from __future__ import annotations

import asyncio
import hashlib
import queue
import re
import subprocess
import threading
import time
from pathlib import Path

import miniaudio


def clean_for_speech(text: str) -> str:
    """Removes markdown and extra characters so the voice does not read junk."""
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"[*_#`>~|]", " ", text)
    text = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:600]


class Speaker:
    """Speech queue: prevents answers from overlapping."""

    def __init__(
        self,
        enabled: bool = True,
        voice: str = "ru-RU-SvetlanaNeural",
        rate: str = "+12%",
        pitch: str = "+120Hz",
        volume: str = "+0%",
        cache_dir: Path | None = None,
    ) -> None:
        self.enabled = enabled
        self.voice = voice
        self.rate = rate
        self.pitch = pitch
        self.volume = volume
        self.lang = "ru"
        self.cache_dir = Path(cache_dir) if cache_dir is not None else Path("logs") / "tts_cache"
        self.cache_dir = Path(self.cache_dir) if not isinstance(self.cache_dir, Path) else self.cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self._queue: queue.Queue[str | None] = queue.Queue()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()
        self._offline = False

    # ------------------------------------------------------------------ api
    def say(self, text: str, lang: str | None = None, blocking: bool = False) -> None:
        text = clean_for_speech(text)
        if not text:
            return
        if not self.enabled:
            return
        lang = lang or self.lang
        self._queue.put((text, lang))
        if blocking:
            self._queue.join()

    def shutdown(self) -> None:
        self._queue.put(None)
        self._thread.join(timeout=10)

    def wait(self, timeout: float = 30.0) -> None:
        """Waits until the speech queue is empty (so we do not hear ourselves)."""
        end = time.monotonic() + timeout
        while self._queue.unfinished_tasks and time.monotonic() < end:
            time.sleep(0.05)

    # ------------------------------------------------------------------ worker
    def _worker(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is None:
                    return
                text, lang = item
                self._speak(text, lang)
            except Exception as exc:  # noqa: BLE001 - speech must not crash the assistant
                print(f"[tts] error: {exc}")
            finally:
                self._queue.task_done()

    def _speak(self, text: str, lang: str) -> None:
        voice = self.voice if lang == "ru" else "en-US-JennyNeural"
        path = self._edge_mp3(text, voice)
        if path is not None:
            try:
                self._play(path)
                return
            except Exception as exc:  # noqa: BLE001 - bad cache/decoder must not crash speech
                print(f"[tts] could not play mp3 ({exc}), trying SAPI")
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
        self._sapi_speak(text, lang)

    # ------------------------------------------------------------------ edge
    def _cache_path(self, text: str, voice: str) -> Path:
        digest = hashlib.sha1(f"{voice}|{self.rate}|{self.pitch}|{text}".encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.mp3"

    def _edge_mp3(self, text: str, voice: str) -> Path | None:
        """Synthesis through Edge TTS with cache. None if network/service is unavailable."""
        cached = self._cache_path(text, voice)
        if cached.exists() and cached.stat().st_size > 512:
            return cached
        if self._offline:
            return None
        try:
            import edge_tts

            async def run() -> None:
                communicate = edge_tts.Communicate(
                    text, voice, rate=self.rate, pitch=self.pitch, volume=self.volume
                )
                await communicate.save(str(cached))

            asyncio.run(run())
            if cached.exists() and cached.stat().st_size > 512:
                return cached
        except Exception as exc:  # noqa: BLE001
            print(f"[tts] Edge unavailable ({type(exc).__name__}), falling back to SAPI")
            self._offline = True
        return None

    # ------------------------------------------------------------------ play
    @staticmethod
    def _play(path: Path) -> None:
        import numpy as np
        import sounddevice as sd

        decoded = miniaudio.decode_file(
            str(path),
            output_format=miniaudio.SampleFormat.SIGNED16,
            nchannels=2,
            sample_rate=44100,
        )
        samples = np.array(decoded.samples, dtype=np.int16)
        if decoded.nchannels > 1:
            samples = samples.reshape(-1, decoded.nchannels)
        sd.play(samples, decoded.sample_rate)
        sd.wait()

    # ------------------------------------------------------------------ sapi
    def _sapi_speak(self, text: str, lang: str = "ru") -> None:
        """Offline fallback: system SAPI."""
        safe = text.replace("'", "''")
        culture = "ru-RU" if lang == "ru" else "en-US"
        script = (
            "Add-Type -AssemblyName System.Speech;"
            "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
            f"$v=$s.GetInstalledVoices()|Where-Object {{$_.VoiceInfo.Culture.Name -like '{culture}*'}}"
            "|Select-Object -First 1;"
            "if($v){$s.SelectVoice($v.VoiceInfo.Name)};"
            f"$s.Speak('{safe}')"
        )
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True,
                timeout=120,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[tts] SAPI failed: {exc}")