"""Timing helpers for edit-selection diagnostics."""

import json
import time
from contextlib import contextmanager


class SelectionTiming:
    """Collect and emit per-phase timings for one edit selection interaction."""

    def __init__(self, interaction, **metadata):
        self.interaction = interaction
        self.metadata = dict(metadata)
        self._start = time.perf_counter()
        self._phases = []

    @contextmanager
    def phase(self, name):
        start = time.perf_counter()
        try:
            yield
        finally:
            self._phases.append((name, (time.perf_counter() - start) * 1000.0))

    def update(self, **metadata):
        self.metadata.update(metadata)

    def add_phase(self, name, duration_ms):
        self._phases.append((name, float(duration_ms)))

    def emit(self, state=None, status="ok"):
        total_ms = (time.perf_counter() - self._start) * 1000.0
        phases = [
            {"name": name, "ms": round(duration_ms, 3)}
            for name, duration_ms in self._phases
        ]
        payload = {
            "interaction": self.interaction,
            "status": status,
            "total_ms": round(total_ms, 3),
            "phases": phases,
            **self.metadata,
        }
        print("[selection-timing] " + json.dumps(payload, sort_keys=True, default=str))
        if state is not None:
            state.selection_timing_payload = payload
            state.selection_timing_last = self._format_summary(total_ms)

    def _format_summary(self, total_ms):
        phase_text = ", ".join(
            f"{name}={duration_ms:.1f} ms" for name, duration_ms in self._phases
        )
        if phase_text:
            return f"{self.interaction}: total={total_ms:.1f} ms ({phase_text})"
        return f"{self.interaction}: total={total_ms:.1f} ms"
