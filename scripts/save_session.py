"""初回セットアップ: 手動ログインしてセッションを storage_state.json に保存する。

使い方:
    python scripts/save_session.py

ブラウザが起動するので、note に手動でログイン（メール/パスワード、
必要なら2段階認証・CAPTCHAも）してください。ログイン完了後、ターミナルで
Enter を押すとセッションが保存されます。以降の自動投稿はこれを再利用します。

セッションが切れたら、再度このスクリプトを実行してください。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright

from src.config import load_config


def main() -> None:
    cfg = load_config()
    login_url = cfg.note.get("login_url", "https://note.com/login")
    out = cfg.storage_state_path

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(login_url)

        print("=" * 60)
        print("ブラウザで note にログインしてください。")
        print("ログインが完了したら、このターミナルで Enter を押してください。")
        print("=" * 60)
        input("ログイン完了後に Enter > ")

        context.storage_state(path=str(out))
        print(f"セッションを保存しました: {out}")
        browser.close()


if __name__ == "__main__":
    main()
