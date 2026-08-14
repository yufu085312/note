"""設定ファイル(config.yaml)と環境変数(.env)のロード。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class FeedConfig:
    url: str
    tags: list[str] = field(default_factory=list)


@dataclass
class Config:
    raw: dict[str, Any]
    feeds: list[FeedConfig]
    max_posts_per_run: int
    draft_only: bool
    append_source: bool
    source_template: str
    formatter: dict[str, Any]
    note: dict[str, Any]

    # env
    gemini_api_key: str | None

    @property
    def storage_state_path(self) -> Path:
        return ROOT / self.note.get("storage_state", "storage_state.json")


def load_config(path: str | Path | None = None) -> Config:
    load_dotenv(ROOT / ".env")
    cfg_path = Path(path) if path else ROOT / "config.yaml"
    if not cfg_path.exists():
        raise FileNotFoundError(
            f"設定ファイルが見つかりません: {cfg_path}\n"
            "config.example.yaml を config.yaml にコピーして編集してください。"
        )
    with cfg_path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    feeds = [
        FeedConfig(url=f["url"], tags=f.get("tags", []))
        for f in raw.get("feeds", [])
    ]

    return Config(
        raw=raw,
        feeds=feeds,
        max_posts_per_run=int(raw.get("max_posts_per_run", 1)),
        draft_only=bool(raw.get("draft_only", True)),
        append_source=bool(raw.get("append_source", True)),
        source_template=raw.get("source_template", "\n\n---\n出典: [{title}]({link})"),
        formatter=raw.get("formatter", {}),
        note=raw.get("note", {}),
        gemini_api_key=os.getenv("GEMINI_API_KEY"),
    )
