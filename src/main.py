"""オーケストレーション: RSS取得 → 重複除外 → 整形 → note投稿。"""
from __future__ import annotations

import argparse
import sys

from .config import Config, FeedConfig, load_config
from .feed import Entry, fetch_all
from .formatter import build_article
from .note_client import NoteClient
from .state import PostedState


def weighted_cycle(feeds: list[FeedConfig]) -> list[str]:
    """weight に応じて発行元(URL)を均等に散らした1周期分の並びを作る。
    例: AINOW(weight=2), ITmedia(weight=1) → [AINOW, ITmedia, AINOW]
    （2:1 の比率で、ITmedia が間に挟まるよう均等配置される）。"""
    slots: list[tuple[float, int, str]] = []
    for idx, f in enumerate(feeds):
        w = max(1, f.weight)
        for k in range(w):
            # 各出現を [0,1) 上に均等配置し、全フィードをまとめて並べ替える
            slots.append(((k + 0.5) / w, idx, f.url))
    slots.sort()
    return [url for _, _, url in slots]


def select_targets(
    new_entries: list[Entry], cfg: Config, seq: list[str], rotation: int
) -> tuple[list[Entry], int]:
    """重み付きローテーション(seq)の rotation 位置から発行元を選び、
    投稿対象と「次回の rotation 位置」を返す。
    目当ての発行元に新規記事が無ければ、seq の次の発行元へ順に回す。"""
    # 発行元ごとに、フィード内の順序を保ったままグループ化
    by_source: dict[str, list[Entry]] = {}
    for e in new_entries:
        by_source.setdefault(e.source, []).append(e)

    if not seq or not by_source:
        return [], rotation

    n = len(seq)
    used: dict[str, int] = {u: 0 for u in by_source}
    targets: list[Entry] = []
    rot = rotation % n

    while len(targets) < cfg.max_posts_per_run:
        picked: str | None = None
        for step in range(n):  # rot から始めて、記事がある発行元を探す
            u = seq[(rot + step) % n]
            if u in by_source and used[u] < len(by_source[u]):
                picked = u
                rot = (rot + step + 1) % n  # 次はこの発行元の次から
                break
        if picked is None:  # どの発行元も拾い切った
            break
        targets.append(by_source[picked][used[picked]])
        used[picked] += 1

    return targets, rot


def _advance_past(seq: list[str], rotation: int, source: str) -> int:
    """seq 上で rotation 位置から見て最初に source が現れる位置の「次」を返す。
    投稿が成功した分だけ rotation を進めるために使う。"""
    n = len(seq)
    if n == 0:
        return rotation
    for step in range(n):
        i = (rotation + step) % n
        if seq[i] == source:
            return (i + 1) % n
    return rotation % n


def run(config_path: str | None, dry_run: bool, headless: bool) -> int:
    cfg = load_config(config_path)
    state = PostedState()

    entries = fetch_all(cfg.feeds)
    new_entries = [e for e in entries if not state.is_posted(e.id)]
    print(f"取得: {len(entries)}件 / 新規: {len(new_entries)}件")

    if not new_entries:
        print("新規記事なし。終了します。")
        return 0

    seq = weighted_cycle(cfg.feeds)
    targets, _ = select_targets(new_entries, cfg, seq, state.rotation)
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

        rot = state.rotation
        for e in targets:
            art = build_article(e, cfg)
            print(f"投稿中: {art.title}")
            try:
                url = client.post(art)
                state.mark(e.id)
                rot = _advance_past(seq, rot, e.source)  # 成功分だけ次へ進める
                state.set_rotation(rot)
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
