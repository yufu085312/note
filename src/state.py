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
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self._ids = set(data.get("posted", []))
            except (json.JSONDecodeError, OSError):
                self._ids = set()

    def is_posted(self, entry_id: str) -> bool:
        return entry_id in self._ids

    def mark(self, entry_id: str) -> None:
        self._ids.add(entry_id)
        self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"posted": sorted(self._ids)}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
