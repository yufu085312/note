"""オーケストレーション: RSS取得 → 重複除外 → 整形 → note投稿。"""
from __future__ import annotations

import argparse
import sys

from .config import Config
from .config import load_config
from .feed import Entry, fetch_all
from .formatter import build_article
from .note_client import NoteClient
from .state import PostedState


def select_targets(
    new_entries: list[Entry], cfg: Config, last_source: str | None
) -> list[Entry]:
    """発行元(フィード)を交互に選ぶラウンドロビンで投稿対象を決める。
    直近に投稿した発行元(last_source)の「次」の発行元から拾い始めるので、
    実行のたびに AINOW → ITmedia → AINOW … と切り替わる。"""
    # 発行元ごとに、フィード内の順序を保ったままグループ化
    by_source: dict[str, list[Entry]] = {}
    for e in new_entries:
        by_source.setdefault(e.source, []).append(e)

    # config.yaml のフィード順を基準にしつつ、新規記事がある発行元だけ残す
    order = [f.url for f in cfg.feeds if f.url in by_source]
    if not order:
        return []

    # 直近に使った発行元の「次」から始まるように回転させる
    if last_source in order:
        i = order.index(last_source)
        order = order[i + 1:] + order[: i + 1]

    targets: list[Entry] = []
    cursor = {u: 0 for u in order}
    while len(targets) < cfg.max_posts_per_run:
        progressed = False
        for u in order:
            if len(targets) >= cfg.max_posts_per_run:
                break
            lst = by_source[u]
            if cursor[u] < len(lst):
                targets.append(lst[cursor[u]])
                cursor[u] += 1
                progressed = True
        if not progressed:  # すべての発行元を拾い切った
            break
    return targets


def run(config_path: str | None, dry_run: bool, headless: bool) -> int:
    cfg = load_config(config_path)
    state = PostedState()

    entries = fetch_all(cfg.feeds)
    new_entries = [e for e in entries if not state.is_posted(e.id)]
    print(f"取得: {len(entries)}件 / 新規: {len(new_entries)}件")

    if not new_entries:
        print("新規記事なし。終了します。")
        return 0

    targets = select_targets(new_entries, cfg, state.last_source)
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

    failures = 0
    with NoteClient(cfg, headless=headless) as client:
        if not client.is_logged_in():
            # セッション期限切れ等。ジョブを失敗(赤)にして通知が届くようにする。
            print("エラー: ログインセッションが無効です（期限切れの可能性）。"
                  "save_session.py を再実行してセッションを更新してください。",
                  file=sys.stderr)
            return 1

        for e in targets:
            art = build_article(e, cfg)
            print(f"投稿中: {art.title}")
            try:
                url = client.post(art)
                state.mark(e.id)
                state.set_last_source(e.source)  # 次回は別の発行元から拾う
                print(f"  完了: {url}")
            except Exception as ex:  # 1件失敗しても他は続けるが、最後に失敗扱いにする
                failures += 1
                print(f"  失敗: {ex}", file=sys.stderr)

    # 1件でも投稿に失敗したらジョブを失敗(赤)にする（成功偽装を防ぐ）
    if failures:
        print(f"エラー: {failures}件の投稿に失敗しました。", file=sys.stderr)
        return 1
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
