"""Распознавание речи локально через faster-whisper (без интернета и лимитов)."""

from __future__ import annotations

import os
import site
from pathlib import Path
from typing import Any

import numpy as np


def _enable_cuda_dlls() -> None:
    """Добавляет в PATH библиотеки cuBLAS/cuDNN из venv (колёса nvidia-*)."""
    folders: list[str] = []
    for base in site.getsitepackages():
        nvidia = Path(base) / "nvidia"
        if not nvidia.is_dir():
            continue
        folders.extend(str(path) for path in nvidia.glob("*/bin"))
    if not folders:
        return
    os.environ["PATH"] = os.pathsep.join(folders + [os.environ.get("PATH", "")])
    for folder in folders:
        try:
            os.add_dll_directory(folder)  # только Windows
        except (AttributeError, OSError):
            pass


class Transcriber:
    """Ленивая обёртка над faster-whisper."""

    def __init__(
        self,
        model_name: str = "small",
        device: str = "auto",
        compute_type: str = "auto",
        language: str | None = None,
        beam_size: int = 1,
        hotwords: str | None = None,
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self.beam_size = beam_size
        self.hotwords = hotwords
        self._model = None

    # ------------------------------------------------------------------ model
    def load(self) -> None:
        if self._model is not None:
            return
        _enable_cuda_dlls()
        from faster_whisper import WhisperModel

        self.effective_language = (
            None if self.language in (None, "auto", "") else self.language
        )

        attempts: list[tuple[str, str]] = []
        if self.device == "auto" and self.compute_type == "auto":
            attempts = [("cuda", "int8_float16"), ("cpu", "int8")]
        elif self.compute_type == "auto":
            attempts = [(self.device, "int8_float16" if self.device == "cuda" else "int8")]
        else:
            attempts = [(self.device, self.compute_type)]

        last_error: Exception | None = None
        for device, compute_type in attempts:
            try:
                print(f"[asr] загружаю модель '{self.model_name}' ({device}/{compute_type})…")
                self._model = WhisperModel(
                    self.model_name,
                    device=device,
                    compute_type=compute_type,
                )
                print(f"[asr] модель готова ({device}/{compute_type})")
                return
            except Exception as exc:  # noqa: BLE001 — нужен любой сбой для фолбэка
                last_error = exc
                print(f"[asr] не вышло с {device}/{compute_type}: {exc}")
        raise RuntimeError(f"Не удалось загрузить модель распознавания: {last_error}")

    # ------------------------------------------------------------------ run
    def transcribe(self, audio: np.ndarray, hotwords: str | None = None) -> str:
        """audio: int16 mono 16 кГц. hotwords: слова-подсказки для модели."""
        self.load()
        assert self._model is not None
        samples = audio.astype(np.float32) / 32768.0
        try:
            return self._run(samples, hotwords)
        except Exception as exc:  # noqa: BLE001 — чаще всего отсутствует CUDA
            print(f"[asr] сбой на {self.device}: {exc}. Перехожу на CPU.")
            self._fallback_to_cpu()
            return self._run(samples, hotwords)

    def _run(self, samples: np.ndarray, hotwords: str | None = None) -> str:
        assert self._model is not None
        kwargs: dict[str, Any] = {
            "beam_size": self.beam_size,
            "vad_filter": False,
            "condition_on_previous_text": False,
            "without_timestamps": True,
        }
        if self.effective_language is not None:
            kwargs["language"] = self.effective_language
        if hotwords:
            kwargs["hotwords"] = hotwords
        segments, _info = self._model.transcribe(samples, **kwargs)
        text = " ".join(segment.text.strip() for segment in segments).strip()
        return " ".join(text.split())

    def _fallback_to_cpu(self) -> None:
        from faster_whisper import WhisperModel

        self._model = WhisperModel(self.model_name, device="cpu", compute_type="int8")
        self.device = "cpu"
        self.compute_type = "int8"
        print("[asr] модель перезагружена на CPU/int8")
