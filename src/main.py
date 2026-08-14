"""オーケストレーション: RSS取得 → 重複除外 → 整形 → note投稿。"""
from __future__ import annotations

import argparse
import sys

from .config import load_config
from .feed import fetch_all
from .formatter import build_article
from .note_client import NoteClient
from .state import PostedState


def run(config_path: str | None, dry_run: bool, headless: bool) -> int:
    cfg = load_config(config_path)
    state = PostedState()

    entries = fetch_all(cfg.feeds)
    new_entries = [e for e in entries if not state.is_posted(e.id)]
    print(f"取得: {len(entries)}件 / 新規: {len(new_entries)}件")

    if not new_entries:
        print("新規記事なし。終了します。")
        return 0

    targets = new_entries[: cfg.max_posts_per_run]
    print(f"今回の投稿対象: {len(targets)}件 (draft_only={cfg.draft_only})")

    if dry_run:
        for e in targets:
            art = build_article(e, cfg)
            print("\n" + "=" * 50)
            print(f"[TITLE] {art.title}")
            print(f"[TAGS ] {art.tags}")
            print(f"[BODY ]\n{art.body[:500]}...")
        print("\n[dry-run] 実際の投稿は行いませんでした。")
        return 0

    with NoteClient(cfg, headless=headless) as client:
        if not client.is_logged_in():
            print("エラー: ログインセッションが無効です。save_session.py を再実行してください。",
                  file=sys.stderr)
            return 1

        for e in targets:
            art = build_article(e, cfg)
            print(f"投稿中: {art.title}")
            try:
                url = client.post(art)
                state.mark(e.id)
                print(f"  完了: {url}")
            except Exception as ex:  # 1件失敗しても他を続ける
                print(f"  失敗: {ex}", file=sys.stderr)

    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="note 自動投稿")
    p.add_argument("-c", "--config", default=None, help="config.yaml のパス")
    p.add_argument("--dry-run", action="store_true", help="投稿せず整形結果だけ表示")
    p.add_argument("--headed", action="store_true", help="ブラウザを表示して実行")
    args = p.parse_args()
    sys.exit(run(args.config, args.dry_run, headless=not args.headed))


if __name__ == "__main__":
    main()
