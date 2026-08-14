# note 自動投稿システム

RSS/Atom フィードから記事を取得し、[note](https://note.com) にブラウザ自動化(Playwright)で自動投稿するツール。定期実行(cron / GitHub Actions)に対応。

> **注意**: note には公式の投稿APIがありません。本ツールは保存済みログインセッションを再利用してブラウザを操作します。UI変更で壊れる可能性があり、利用は [note の利用規約](https://note.com/terms) の範囲内で自己責任で行ってください。まずは `draft_only: true`（下書き保存のみ）での運用を推奨します。

## 仕組み

```
RSS取得 → 重複除外 → 元記事本文をフル取得 → Gemini(無料)でオリジナル記事生成 → note投稿(Playwright)
```

`use_ai: true`（既定）では、RSSの各記事について元ページから本文を抽出し、**Google Gemini（無料枠）** がトピックを咀嚼して note 向けのオリジナル記事（タイトル・本文・タグ）を生成します。出典リンクも自動付与します。`use_ai: false` にすると RSS 要約をそのまま使います（丸写しになるため下書き確認推奨）。

| ファイル | 役割 |
|---|---|
| `src/feed.py` | RSS/Atom の取得・パース |
| `src/formatter.py` | フィード項目 → note記事へ整形（AI要約は任意） |
| `src/note_client.py` | Playwright による note 操作（ログイン/下書き/公開） |
| `src/state.py` | 投稿済み管理（二重投稿防止） |
| `src/main.py` | 全体の実行 |
| `scripts/save_session.py` | 初回ログイン＆セッション保存 |

## セットアップ

```bash
# 1. 依存インストール
pip install -r requirements.txt
python -m playwright install chromium

# 2. 設定ファイルを用意
cp config.example.yaml config.yaml   # feeds などを編集
cp .env.example .env                  # 必要なら編集

# 3. 初回ログイン（ブラウザが開くので手動ログイン → Enter）
python scripts/save_session.py
```

## 使い方

```bash
# 整形結果だけ確認（投稿しない）
python -m src.main --dry-run

# ブラウザを表示して実行（デバッグ用）
python -m src.main --headed

# 通常実行（config の draft_only / max_posts_per_run に従う）
python -m src.main
```

## 設定 (`config.yaml`)

- `feeds`: 取得する RSS の URL とタグ
- `max_posts_per_run`: 1回の実行で投稿する最大件数（事故防止）
- `draft_only`: `true` で下書き保存のみ（**最初はこれを推奨**）
- `formatter.use_ai`: `true`（既定）で Gemini によるオリジナル記事生成を有効化（`.env` に `GEMINI_API_KEY` が必要。[無料キー取得](https://aistudio.google.com/apikey)）
- `formatter.fetch_full_content`: `true` で元記事ページから本文をフル取得してAIに渡す
- `formatter.model`: `gemini-2.5-flash`（無料枠・推奨）/ `gemini-2.0-flash`
- `note.selectors`: note エディタのDOMセレクタ（壊れたらここを調整）

## 定期自動実行

### GitHub Actions
`.github/workflows/post.yml` が毎日実行します。以下の Secret を登録してください:

- `STORAGE_STATE_JSON`: `base64 -i storage_state.json` の出力（ログインセッション）
- `GEMINI_API_KEY`: AI生成を使う場合（無料キー）

> セッションには有効期限があります。切れたらローカルで `save_session.py` を再実行し、Secret を更新してください。

### ローカル cron（例: 毎日9時）
```cron
0 9 * * * cd /path/to/note && /path/to/python -m src.main >> post.log 2>&1
```

## 既知の制約

- note のエディタUI変更でセレクタが壊れることがあります（`config.yaml` で調整可能）。
- 本文はプレーンテキストとして入力されます（Markdownの見出し等は反映されません）。
- 2段階認証/CAPTCHA がある場合、セッション再取得は手動が必要です。
