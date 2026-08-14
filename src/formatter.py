"""フィード項目を note 記事(タイトル/本文/タグ)に整形する。

use_ai=true の場合:
  1. 元記事の本文をフル取得（RSS要約は短いため）
  2. Claude でトピックを抽出し、note読者向けのオリジナル記事を生成
  3. 出典を明記（著作権配慮）

use_ai=false の場合:
  RSSの要約テキストをそのまま整形（丸写しになるため下書き確認推奨）
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .config import Config
from .feed import Entry, fetch_article_text


@dataclass
class Article:
    title: str
    body: str          # プレーンテキスト（1行=1段落として入力される）
    tags: list[str] = field(default_factory=list)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


_SYSTEM = (
    "あなたはプロのブロガーです。与えられたニュース記事の内容をもとに、"
    "note読者向けの日本語のオリジナル記事を書きます。"
    "元記事を丸写しせず、要点を咀嚼して自分の言葉で再構成・解説してください。"
    "事実に基づき、誇張や捏造はしないこと。"
)


def _generate_with_ai(entry: Entry, source_text: str, cfg: Config) -> Article:
    """Gemini(無料枠) でオリジナル記事(タイトル/本文/タグ)を生成する。"""
    from google import genai
    from google.genai import types
    from pydantic import BaseModel, Field

    class GeneratedArticle(BaseModel):
        title: str = Field(description="読者の興味を引く記事タイトル")
        body: str = Field(description="段落ごとに改行したプレーンテキスト本文。見出し記号は使わない")
        tags: list[str] = Field(description="noteのハッシュタグを2〜4個", default_factory=list)

    if not cfg.gemini_api_key:
        raise RuntimeError(
            "GEMINI_API_KEY が未設定です。.env に設定してください。"
            "無料キー: https://aistudio.google.com/apikey"
        )

    client = genai.Client(api_key=cfg.gemini_api_key)
    model = cfg.formatter.get("model", "gemini-2.5-flash")
    target_chars = int(cfg.formatter.get("max_body_chars", 4000))

    prompt = (
        f"以下のニュースをもとに、note向けのオリジナル記事を書いてください。\n"
        f"本文は約{target_chars}文字以内、段落ごとに改行したプレーンテキストで。\n\n"
        f"元記事タイトル: {entry.title}\n"
        f"元記事URL: {entry.link}\n\n"
        f"元記事の内容:\n{source_text}"
    )

    resp = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=_SYSTEM,
            response_mime_type="application/json",
            response_schema=GeneratedArticle,
            # 構造化出力のみ利用。AFC(自動関数呼び出し)は使わないので無効化し警告を抑止
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        ),
    )
    gen: GeneratedArticle = resp.parsed

    # フィード設定のタグとAI提案タグをマージ（重複除去・順序維持）
    tags = list(dict.fromkeys([*entry.tags, *(gen.tags or [])]))
    return Article(title=gen.title.strip(), body=gen.body.strip(), tags=tags)


def build_article(entry: Entry, cfg: Config) -> Article:
    max_chars = int(cfg.formatter.get("max_body_chars", 4000))

    if cfg.formatter.get("use_ai"):
        # 元記事本文をフル取得（失敗時はRSS要約でフォールバック）
        source_text = ""
        if cfg.formatter.get("fetch_full_content", True):
            source_text = fetch_article_text(entry.link)
        if not source_text:
            source_text = entry.summary
        article = _generate_with_ai(entry, source_text, cfg)
    else:
        article = Article(title=entry.title, body=entry.summary, tags=list(entry.tags))

    article.body = _truncate(article.body, max_chars)

    if cfg.append_source and entry.link:
        article.body += cfg.source_template.format(title=entry.title, link=entry.link)

    return article
