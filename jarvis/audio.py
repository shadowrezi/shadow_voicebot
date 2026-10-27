"""Microphone capture, wake word (openWakeWord) and voice activity detection (Silero VAD)."""

from __future__ import annotations

import collections
import threading
import time
import warnings
from typing import Any

import numpy as np

# Suppress torch.jit.load FutureWarning from silero-vad
warnings.filterwarnings("ignore", message=".*torch.jit.load.*", category=FutureWarning)
import sounddevice as sd


def list_input_devices() -> list[dict[str, Any]]:
    """Returns the list of input devices with indices."""
    result: list[dict[str, Any]] = []
    for index, info in enumerate(sd.query_devices()):
        if info["max_input_channels"] > 0:
            result.append(
                {
                    "index": index,
                    "name": info["name"],
                    "channels": info["max_input_channels"],
                    "default": index == sd.default.device[0],
                }
            )
    return result


class Mic:
    """Microphone stream.

    Supports wake word (openWakeWord "hey_jarvis") and phrase recording (Silero VAD).
    Activation via hotkey (Ctrl+Alt+J) through _activation_event.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        device: int | str | None = None,
        silence_ms: int = 700,
        max_phrase_s: float = 20.0,
        min_rms: float = 220.0,
        pre_roll_ms: int = 300,
        block_ms: int = 30,
        vad_threshold: float = 0.5,
        wake_word_threshold: float = 0.3,
        wake_word_enabled: bool = False,
    ) -> None:
        self.sample_rate = sample_rate
        self.device = device
        self.silence_ms = silence_ms
        self.max_phrase_s = max_phrase_s
        self.min_rms = min_rms
        self.pre_roll_ms = pre_roll_ms
        self.block_ms = block_ms
        self.vad_threshold = vad_threshold
        self.wake_word_threshold = wake_word_threshold
        self.wake_word_enabled = wake_word_enabled

        self._stream: sd.RawInputStream | None = None
        self._vad_model = None
        self._vad_get_speech_timestamps = None
        self._wake_model = None
        self._asr_for_wake = None
        self._activation_event: threading.Event = threading.Event()
        self._speech_start: float | None = None

    # ------------------------------------------------------------------ stream
    def open(self) -> None:
        if self._stream is not None:
            return
        self._stream = sd.RawInputStream(
            samplerate=self.sample_rate,
            blocksize=int(self.sample_rate * self.block_ms / 1000),
            device=self.device,
            dtype="int16",
            channels=1,
        )
        self._stream.start()

    def close(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            finally:
                self._stream = None

    def __enter__(self) -> "Mic":
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ helpers
    def _read_block(self) -> np.ndarray:
        assert self._stream is not None, "Microphone is not open"
        data, _overflowed = self._stream.read(int(self.sample_rate * self.block_ms / 1000))
        return np.frombuffer(data, dtype=np.int16)

    @staticmethod
    def _rms(block: np.ndarray) -> float:
        if block.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(np.square(block.astype(np.float32)))))

    @property
    def noise_floor(self) -> float:
        return getattr(self, "_noise_floor", 0.0)

    @property
    def threshold(self) -> float:
        return self.min_rms

    def calibrate(self, seconds: float = 1.2) -> float:
        """Measures background noise and sets the trigger threshold."""
        self.open()
        samples: list[float] = []
        blocks = max(1, int(seconds * 1000 / self.block_ms))
        for _ in range(blocks):
            samples.append(self._rms(self._read_block()))
        samples.sort()
        self._noise_floor = samples[len(samples) // 2]
        return self._noise_floor

    # ------------------------------------------------------------------ activation by hotkey
    def activate(self) -> None:
        """Marks that the user pressed the activation hotkey."""
        self._activation_event.set()

    def wait_for_activation(self, timeout: float | None = None) -> bool:
        """Blocks the thread until the activation hotkey is pressed.

        Returns True if activation happened, False if the timeout expired.
        """
        got = self._activation_event.wait(timeout)
        if got:
            self._activation_event.clear()
        return got

    # ------------------------------------------------------------------ wake word
    def _load_wake_model(self) -> None:
        """Lazy load of openWakeWord "hey_jarvis"."""
        if self._wake_model is not None or not self.wake_word_enabled:
            return
        try:
            from openwakeword.model import Model

            self._wake_model = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
        except Exception:  # noqa: BLE001
            self._wake_model = None

    def wait_for_wake_word(self, timeout: float | None = None) -> bool:
        """Continuously listens to the microphone and waits for the wake word or hotkey.

        Returns True if activated.
        """
        if not self.wake_word_enabled:
            # Wake word disabled - wait for the hotkey.
            deadline = None if timeout is None else time.monotonic() + timeout
            while True:
                if self._activation_event is not None and self._activation_event.is_set():
                    self._activation_event.clear()
                    return True
                if deadline is not None and time.monotonic() > deadline:
                    return False
                time.sleep(0.1)

        self._load_wake_model()
        self.open()

        asr_buffer: list[np.ndarray] = []
        last_asr_check = time.monotonic()
        asr_check_interval = 0.5
        _speech_start: float | None = None

        deadline = None if timeout is None else time.monotonic() + timeout
        frame_size = 1280  # 80 ms at 16 kHz

        while True:
            # Check the activation event (hotkey).
            if self._activation_event is not None and self._activation_event.is_set():
                self._activation_event.clear()
                return True

            if deadline is not None and time.monotonic() > deadline:
                return False

            # Read blocks until 1280 samples are collected
            frames: list[np.ndarray] = []
            collected = 0
            while collected < frame_size:
                block = self._read_block()
                frames.append(block)
                collected += len(block)

            audio = np.concatenate(frames)
            if len(audio) > frame_size:
                audio = audio[:frame_size]

            # 1. openWakeWord (hey jarvis) - low threshold for reliability
            if self._wake_model is not None:
                try:
                    prediction = self._wake_model.predict(audio)
                    score = prediction.get("hey_jarvis", 0.0)
                    if score >= self.wake_word_threshold:
                        return True
                except Exception:  # noqa: BLE001
                    pass

            # 2. ASR check for shadow/шедоу/джарвис
            asr_buffer.append(audio)
            now = time.monotonic()
            if now - last_asr_check >= asr_check_interval:
                last_asr_check = now
                try:
                    buf_audio = np.concatenate(asr_buffer)
                    if len(buf_audio) >= self.sample_rate * 0.5:
                        # Lazy ASR init
                        if self._asr_for_wake is None:
                            from jarvis.asr import Transcriber

                            self._asr_for_wake = Transcriber(
                                model_name="small", language=None, device="auto", compute_type="auto"
                            )
                            self._asr_for_wake.load()
                        text = self._asr_for_wake.transcribe(buf_audio)
                        text_lower = text.lower()
                        if text_lower.strip():
                            print(f"[wake] ASR: {text_lower!r}", flush=True)
                        # Check wake word variants
                        wake_variants = [
                            "shadow", "шедоу", "шэдоу", "шадоу",
                            "jardis", "jorvis", "jarvis", "jarvix", "jarvizz",
                            "джарвис", "джарвиз", "джарвису", "джарвиз",
                            "hey", "хей", "хэй",
                        ]
                        for variant in wake_variants:
                            if variant in text_lower:
                                return True
                        # Fuzzy check: any word with ratio >= 0.4
                        import difflib

                        for word in text_lower.split():
                            for variant in wake_variants:
                                if difflib.SequenceMatcher(None, word, variant).ratio() >= 0.4:
                                    return True
                        # Fallback: if any speech is detected for 1+ sec, trigger too
                        if len(buf_audio) >= self.sample_rate * 1.0 and len(text_lower.strip()) > 0:
                            return True
                    asr_buffer.clear()
                except Exception:  # noqa: BLE001
                    asr_buffer.clear()

            # 3. Fallback: if Silero VAD detects speech for more than 1 sec, activate
            if self._has_speech(audio):
                if self._speech_start is None:
                    self._speech_start = time.monotonic()
                if time.monotonic() - self._speech_start >= 1.0:
                    return True
            else:
                self._speech_start = None

    # ------------------------------------------------------------------ VAD
    def _load_vad(self) -> None:
        """Lazy load of Silero VAD."""
        if self._vad_model is not None:
            return
        try:
            from silero_vad import load_silero_vad, get_speech_timestamps

            self._vad_model = load_silero_vad()
            self._vad_get_speech_timestamps = get_speech_timestamps
        except Exception:  # noqa: BLE001
            self._vad_model = None
            self._vad_get_speech_timestamps = None

    def _has_speech(self, audio: np.ndarray) -> bool:
        """Returns True if the fragment contains speech (Silero VAD)."""
        self._load_vad()
        if self._vad_model is None or self._vad_get_speech_timestamps is None:
            return self._rms(audio) >= self.min_rms
        try:
            samples = audio.astype(np.float32) / 32768.0
            timestamps = self._vad_get_speech_timestamps(
                samples,
                self._vad_model,
                sampling_rate=self.sample_rate,
                threshold=self.vad_threshold,
                return_seconds=False,
            )
            return len(timestamps) > 0
        except Exception:  # noqa: BLE001
            return self._rms(audio) >= self.min_rms

    # ------------------------------------------------------------------ record
    def record_phrase(self, wait_timeout: float | None = None) -> np.ndarray | None:
        """Waits for speech and returns it as an int16 array.

        wait_timeout: seconds to wait for speech to start (None - forever).
        """
        self.open()
        pre_roll: collections.deque[np.ndarray] = collections.deque(
            maxlen=max(1, int(self.pre_roll_ms / self.block_ms))
        )
        silence_blocks = max(1, int(self.silence_ms / self.block_ms))
        max_blocks = max(1, int(self.max_phrase_s * 1000 / self.block_ms))

        started_at: float | None = None
        chunks: list[np.ndarray] = []
        quiet_run = 0
        deadline = None if wait_timeout is None else time.monotonic() + wait_timeout

        while True:
            block = self._read_block()
            loud = self._has_speech(block) or self._rms(block) >= self.min_rms

            if started_at is None:
                pre_roll.append(block)
                if loud:
                    started_at = time.monotonic()
                    chunks.extend(pre_roll)
                    chunks.append(block)
                elif deadline is not None and time.monotonic() > deadline:
                    return None
                continue

            chunks.append(block)
            if loud:
                quiet_run = 0
            else:
                quiet_run += 1
            if quiet_run >= silence_blocks:
                break
            if len(chunks) >= max_blocks:
                break

        if started_at is None:
            return None
        # Trim trailing silence, leaving a small margin.
        if quiet_run > 0 and len(chunks) > quiet_run:
            chunks = chunks[: len(chunks) - max(0, quiet_run - 2)]
        audio = np.concatenate(chunks)
        if audio.size < self.sample_rate * 0.12:  # shorter than 120 ms - junk
            return None
        return audio