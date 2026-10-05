"""Pausenerkennung (lokal, Silero VAD über sherpa-onnx): schneidet den Audiostrom in Äußerungen."""

from __future__ import annotations

import numpy as np

from .config import EINST, WURZEL

RATE = 16000
FENSTER = 512  # Silero arbeitet in 512er-Schritten


class Pausenerkennung:
    def __init__(self) -> None:
        import sherpa_onnx

        cfg = sherpa_onnx.VadModelConfig()
        cfg.silero_vad.model = str(WURZEL / "modelle" / EINST.vad_modell)
        cfg.silero_vad.threshold = 0.5
        cfg.silero_vad.min_silence_duration = EINST.vad_pause_sekunden
        cfg.silero_vad.min_speech_duration = 0.3
        cfg.silero_vad.max_speech_duration = EINST.vad_max_sekunden
        cfg.sample_rate = RATE
        self._vad = sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=120)
        self._rest = np.zeros(0, dtype=np.float32)

    @property
    def spricht(self) -> bool:
        return bool(self._vad.is_speech_detected())

    def zufuehren(self, proben: np.ndarray) -> list[tuple[float, float, np.ndarray]]:
        """16-kHz-Proben (float32) hinein, fertige Äußerungen (start, ende, proben) heraus."""
        daten = np.concatenate([self._rest, proben])
        n = len(daten) // FENSTER * FENSTER
        for i in range(0, n, FENSTER):
            self._vad.accept_waveform(daten[i:i + FENSTER])
        self._rest = daten[n:]
        return self._abholen()

    def ende(self) -> list[tuple[float, float, np.ndarray]]:
        self._vad.flush()
        return self._abholen()

    def _abholen(self) -> list[tuple[float, float, np.ndarray]]:
        fertig = []
        while not self._vad.empty():
            s = self._vad.front
            proben = np.array(s.samples, dtype=np.float32)
            fertig.append((s.start / RATE, (s.start + len(proben)) / RATE, proben))
            self._vad.pop()
        return fertig
