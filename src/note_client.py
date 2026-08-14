"""Playwright による note の投稿自動化。

note には公式APIが無いため、保存済みセッション(storage_state.json)を
再利用してブラウザを操作する。セッションは scripts/save_session.py で作成する。

エディタのDOMは変更されやすい。セレクタは config.yaml の note.selectors で
調整できる。壊れたら save_session.py の --inspect でページ構造を確認すること。
"""
from __future__ import annotations

import time
from pathlib import Path

from playwright.sync_api import Page, TimeoutError as PWTimeout, sync_playwright

from .config import Config
from .formatter import Article


class NoteClient:
    def __init__(self, cfg: Config, headless: bool = True):
        self.cfg = cfg
        self.headless = headless
        self.sel = cfg.note.get("selectors", {})
        self._pw = None
        self._browser = None
        self._context = None
        self.page: Page | None = None

    # ---- ライフサイクル ----
    def __enter__(self) -> "NoteClient":
        state = self.cfg.storage_state_path
        if not state.exists():
            raise FileNotFoundError(
                f"セッションが未保存です: {state}\n"
                "先に `python scripts/save_session.py` を実行してログインしてください。"
            )
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=self.headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        # 実ブラウザらしく見せる（anti-bot対策・描画安定化）
        self._context = self._browser.new_context(
            storage_state=str(state),
            viewport={"width": 1280, "height": 900},
            locale="ja-JP",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        self.page = self._context.new_page()
        return self

    def __exit__(self, *exc) -> None:
        for closer in (self._context, self._browser):
            try:
                if closer:
                    closer.close()
            except Exception:
                pass
        if self._pw:
            self._pw.stop()

    # ---- 投稿 ----
    def is_logged_in(self) -> bool:
        assert self.page
        self.page.goto("https://note.com/", wait_until="domcontentloaded")
        # ログイン時のみ出る要素（投稿ボタン等）を確認
        try:
            self.page.wait_for_selector(
                "a[href*='/notes/new'], button:has-text('投稿')", timeout=5000
            )
            return True
        except PWTimeout:
            return False

    def post(self, article: Article) -> str:
        """記事を投稿し、結果URL（取得できれば）を返す。"""
        assert self.page
        page = self.page
        page.goto(self.cfg.note.get("editor_url", "https://note.com/notes/new"),
                  wait_until="domcontentloaded")
        # SPAのエディタ描画完了を待つ（ネットワーク静止 + 保険のsleep）
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except PWTimeout:
            pass
        time.sleep(2)

        # タイトル（CI/headlessでの描画遅延に備えて長めのタイムアウト）
        title_el = page.wait_for_selector(self.sel["title"], timeout=30000)
        title_el.click()
        title_el.fill(article.title)

        # 本文: contenteditable に段落ごとに入力
        body_el = page.wait_for_selector(self.sel["body"], timeout=30000)
        body_el.click()
        for i, para in enumerate(article.body.split("\n")):
            if i > 0:
                page.keyboard.press("Enter")
            if para:
                page.keyboard.type(para, delay=8)

        time.sleep(1)  # 自動保存の反映待ち

        if self.cfg.draft_only:
            return self._save_draft(page)
        return self._publish(page, article.tags)

    def _save_draft(self, page: Page) -> str:
        btn = self.sel.get("save_draft_button")
        if btn:
            try:
                page.click(btn, timeout=8000)
                time.sleep(2)
            except PWTimeout:
                pass
        # note は入力時点で自動的に下書き保存される
        return page.url

    def _publish(self, page: Page, tags: list[str]) -> str:
        page.click(self.sel["publish_button"], timeout=15000)
        time.sleep(1)

        # タグ入力（公開設定ダイアログ内。UI変更に弱いので best-effort）
        for tag in tags:
            try:
                tag_input = page.wait_for_selector(
                    "input[placeholder*='ハッシュタグ'], input[placeholder*='タグ']",
                    timeout=4000,
                )
                tag_input.fill(tag)
                page.keyboard.press("Enter")
            except PWTimeout:
                break

        page.click(self.sel["publish_confirm"], timeout=15000)
        page.wait_for_load_state("networkidle")
        time.sleep(2)
        return page.url
