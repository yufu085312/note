"""投稿済み記事の管理。二重投稿を防ぐ。"""
from __future__ import annotations

import json
from pathlib import Path

from .config import ROOT

STATE_PATH = ROOT / "data" / "posted.json"


class PostedState:
    def __init__(self, path: Path = STATE_PATH):
        self.path = path
        self._ids: set[str] = set()
        self._last_source: str | None = None  # 直近に投稿した発行元(フィードURL)
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self._ids = set(data.get("posted", []))
                self._last_source = data.get("last_source")
            except (json.JSONDecodeError, OSError):
                self._ids = set()
                self._last_source = None

    def is_posted(self, entry_id: str) -> bool:
        return entry_id in self._ids

    def mark(self, entry_id: str) -> None:
        self._ids.add(entry_id)
        self._save()

    @property
    def last_source(self) -> str | None:
        return self._last_source

    def set_last_source(self, source: str) -> None:
        self._last_source = source
        self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {"posted": sorted(self._ids), "last_source": self._last_source},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
