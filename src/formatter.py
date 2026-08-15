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


_SYSTEM = """あなたは月間数万PVを集める人気ブロガーです。時事ニュースを分かりやすく
解説することで知られています。ニュースを元に、note読者が「読んでよかった」と思う
質の高いオリジナル記事を書きます。話題はテックに限らず、政治・経済・社会・国際・
科学・スポーツなど何でも扱います。

# 守ること
- 元記事の丸写しは厳禁。事実(数字・固有名詞・出来事)は正確に踏まえつつ、要点を咀嚼し、
  背景・意味・読者にとっての価値を自分の言葉で解説する。
- 事実に基づき、誇張・断定のしすぎ・捏造をしない。推測は「〜と考えられます」と明示。
- 専門用語は噛み砕く。具体例やたとえを使い、初心者にも分かるように。

# 文章のスタイル
- 親しみやすく、しかし中身のある「です・ます」調。冗長な前置きや決まり文句は避ける。
- 単なる要約ではなく、「なぜ重要か」「読者にどう関係するか」という視点を必ず入れる。
- スマホでの読みやすさを最優先。1つの段落は2〜3文(長くても4文)までに収め、
  話の区切りごとにこまめに空行で改行する。1段落を長い文章の塊にしない。

# 構成(この流れで書く)
1. リード: 読者を引き込む導入(2〜3文)。何の話で、なぜ面白いのかを提示。
2. 本論: 「## 見出し」で2〜3個のセクションに分け、各セクションで背景・詳細・意義を解説。
3. まとめ: 要点の再確認と、読者への一言(問いかけや今後の展望)。

# noteの記法(本文にそのまま書いてよい)
- セクション見出しは行頭に「## 」を付ける(例: ## そもそも何が変わったのか)。
- 段落と段落の間は空行で区切る。
- 箇条書き記号(「- 」など)や強調記号は使わない。要点は文章で表現する。"""


def _generate_with_ai(entry: Entry, source_text: str, cfg: Config) -> Article:
    """Gemini(無料枠) でオリジナル記事(タイトル/本文/タグ)を生成する。"""
    from google import genai
    from google.genai import types
    from pydantic import BaseModel, Field

    class GeneratedArticle(BaseModel):
        title: str = Field(
            description="30字前後の具体的で魅力的なタイトル。煽りすぎず内容を的確に表す"
        )
        body: str = Field(
            description=(
                "記事本文。リード→「## 見出し」で区切った本論2〜3節→まとめ、の構成。"
                "1段落は2〜3文までに短く区切り、段落間は空行で改行する(スマホで読みやすく)。"
                "見出しは行頭『## 』。箇条書き記号や強調記号は使わない"
            )
        )
        tags: list[str] = Field(
            description="内容に即したnoteのハッシュタグを3〜5個", default_factory=list
        )

    if not cfg.gemini_api_key:
        raise RuntimeError(
            "GEMINI_API_KEY が未設定です。.env に設定してください。"
            "無料キー: https://aistudio.google.com/apikey"
        )

    client = genai.Client(api_key=cfg.gemini_api_key)
    model = cfg.formatter.get("model", "gemini-2.5-flash")
    target_chars = int(cfg.formatter.get("max_body_chars", 4000))
    max_tokens = int(cfg.formatter.get("max_output_tokens", 8192))

    image_rule = ""
    if cfg.formatter.get("image_placeholders", True):
        image_rule = (
            "\n# 画像の目印\n"
            "本文中の区切りの良い位置(リード直後や各セクションの冒頭など)に、"
            "後から手動で画像を挿入するための目印を2〜3箇所入れてください。\n"
            "形式は必ず、その位置に合う画像の内容の説明と、画像の下に添えるキャプション文を"
            "1行にまとめた次の形とすること:\n"
            "『【画像候補】<画像の内容の説明> ｜ キャプション：<画像下に添える短い説明文>』\n"
            "(例: 【画像候補】冠水した市街地の道路のイメージ ｜ キャプション：記録的な大雨で"
            "冠水した街の様子)\n"
            "実在の報道写真の指定ではなく、内容に合う一般的な画像イメージを説明する。\n"
        )

    prompt = (
        "以下のニュースを元に、上記の役割・構成・スタイルに従って"
        "note向けのオリジナル記事を書いてください。\n"
        f"本文の分量は{max(1200, target_chars - 700)}〜{target_chars}文字程度を目安に、"
        "内容の薄い水増しはせず、簡潔で読み応えのある密度で書いてください。\n"
        f"{image_rule}\n"
        f"# 元記事タイトル\n{entry.title}\n\n"
        f"# 元記事URL\n{entry.link}\n\n"
        f"# 元記事の内容\n{source_text}"
    )

    resp = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=_SYSTEM,
            response_mime_type="application/json",
            response_schema=GeneratedArticle,
            max_output_tokens=max_tokens,
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
