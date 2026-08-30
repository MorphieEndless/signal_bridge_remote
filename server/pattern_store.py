"""
Signal Bridge Remote — Persistent Pattern Library

Server-side storage for named custom waveforms. Lets an AI client save a
favourite pattern once and replay it later by name via play_pattern.

Patterns are stored per user as JSON files under config.PATTERNS_DIR.
Validation mirrors the phone's custom_pattern checks (CommandDispatcher.kt):
  - 1..128 steps
  - each step duration_ms >= 100
  - repeat 1..20
  - total duration (sum(steps) * repeat) <= 10 minutes
The phone re-validates on receipt — the server is the first gate, not the last.
"""
from __future__ import annotations
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from . import config

log = logging.getLogger("signal_bridge.patterns")

MIN_STEP_MS = 100
MAX_STEPS = 128
MAX_REPEAT = 20
MAX_TOTAL_MS = 10 * 60 * 1000  # 10 minutes


class PatternStep(BaseModel):
    """One step of a custom waveform. vibrate/constrict are normalized 0-1."""
    duration_ms: int = Field(ge=MIN_STEP_MS)
    vibrate: float = Field(0.0, ge=0.0, le=1.0)
    constrict: float = Field(0.0, ge=0.0, le=1.0)
    constrict_mode: Optional[int] = Field(None, ge=1, le=8)  # suction byte4


class StoredPattern(BaseModel):
    """A named, server-side custom waveform."""
    id: str
    name: str
    description: str = ""
    device: str = "yingti"
    repeat: int = Field(1, ge=1, le=MAX_REPEAT)
    intensity_scale: float = Field(1.0, ge=0.0, le=1.0)
    steps: list[PatternStep]
    created_at: float = 0.0
    updated_at: float = 0.0

    def total_ms(self) -> int:
        """Total runtime in ms including repeats."""
        return sum(s.duration_ms for s in self.steps) * self.repeat

    def peak_intensity(self) -> float:
        """Highest intensity across both channels (for governor heat)."""
        return max([0.0] + [s.vibrate for s in self.steps] + [s.constrict for s in self.steps])


class PatternStore:
    """Per-user JSON-file pattern storage. One file per user id."""

    def __init__(self, root: str):
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, user_id: str) -> Path:
        # user_id is a uuid hex from the DB, but sanitize anyway
        safe = "".join(c for c in user_id if c.isalnum() or c in "-_")
        return self._root / f"{safe}.json"

    def _load(self, user_id: str) -> list[StoredPattern]:
        path = self._path(user_id)
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return [StoredPattern(**item) for item in data]
        except Exception as exc:  # corrupt file should not kill the server
            log.error("Failed to load patterns for %s: %s", user_id, exc)
            return []

    def _save(self, user_id: str, patterns: list[StoredPattern]) -> None:
        path = self._path(user_id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(
                [p.model_dump() for p in patterns],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        tmp.replace(path)

    # ── CRUD ────────────────────────────────────────────────────────────

    def list(self, user_id: str) -> list[dict]:
        return [p.model_dump() for p in self._load(user_id)]

    def get(self, user_id: str, name_or_id: str) -> Optional[StoredPattern]:
        key = name_or_id.strip().lower()
        for pattern in self._load(user_id):
            if pattern.id == key or pattern.name.lower() == key:
                return pattern
        return None

    def create(
        self,
        user_id: str,
        name: str,
        steps: list[dict],
        repeat: int = 1,
        intensity_scale: float = 1.0,
        description: str = "",
        device: str = "yingti",
    ) -> StoredPattern:
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("name is required")
        if len(clean_name) > 64:
            raise ValueError("name must be at most 64 characters")

        parsed_steps = [PatternStep(**step) for step in steps]
        if not 1 <= len(parsed_steps) <= MAX_STEPS:
            raise ValueError(f"steps must contain 1-{MAX_STEPS} items")
        if not 1 <= repeat <= MAX_REPEAT:
            raise ValueError(f"repeat must be 1-{MAX_REPEAT}")
        total = sum(s.duration_ms for s in parsed_steps) * repeat
        if total > MAX_TOTAL_MS:
            raise ValueError(
                f"pattern may run for at most {MAX_TOTAL_MS // 60_000} minutes "
                f"(got {total / 1000:.0f}s)"
            )

        patterns = self._load(user_id)
        if any(p.name.lower() == clean_name.lower() for p in patterns):
            raise ValueError(f"a pattern named '{clean_name}' already exists")

        now = time.time()
        pattern = StoredPattern(
            id=uuid.uuid4().hex[:12],
            name=clean_name,
            description=description.strip(),
            device=device,
            repeat=repeat,
            intensity_scale=max(0.0, min(1.0, intensity_scale)),
            steps=parsed_steps,
            created_at=now,
            updated_at=now,
        )
        patterns.append(pattern)
        self._save(user_id, patterns)
        log.info("Pattern '%s' created for user %s (%d steps x %d)",
                 pattern.name, user_id, len(pattern.steps), pattern.repeat)
        return pattern

    def delete(self, user_id: str, name_or_id: str) -> bool:
        key = name_or_id.strip().lower()
        patterns = self._load(user_id)
        remaining = [
            p for p in patterns
            if p.id != key and p.name.lower() != key
        ]
        if len(remaining) == len(patterns):
            return False
        self._save(user_id, remaining)
        log.info("Pattern '%s' deleted for user %s", name_or_id, user_id)
        return True


# Singleton — created at import time, root dir ensured
pattern_store = PatternStore(config.PATTERNS_DIR)
