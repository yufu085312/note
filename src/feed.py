"""RSS/Atom フィードの取得とパース。"""
from __future__ import annotations

import hashlib
import ssl
import urllib.request
from dataclasses import dataclass

import feedparser
from bs4 import BeautifulSoup

from .config import FeedConfig

# macOS の Python.org 版はシステムのルート証明書を参照できないことがあるため、
# certifi の CA バンドルで明示的に SSL コンテキストを作る。
try:
    import certifi

    _SSL_CTX: ssl.SSLContext | None = ssl.create_default_context(cafile=certifi.where())
except Exception:  # certifi 未導入でもデフォルト挙動で動くようにする
    _SSL_CTX = None

_UA = "Mozilla/5.0 (compatible; note-auto-post/1.0)"


def _fetch(url: str) -> bytes | str:
    """URL からフィードの生データを取得。file:// やローカルパスはそのまま返す。"""
    if not url.startswith(("http://", "https://")):
        return url  # ローカルファイル/パスは feedparser に委ねる
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, context=_SSL_CTX, timeout=30) as resp:
        return resp.read()


@dataclass
class Entry:
    id: str          # 重複排除用の安定ID
    title: str
    link: str
    summary: str     # プレーンテキスト本文
    tags: list[str]  # フィード設定由来のタグ


def _stable_id(entry: feedparser.FeedParserDict) -> str:
    raw = entry.get("id") or entry.get("link") or entry.get("title", "")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


_BLOCK_TAGS = ["p", "div", "li", "br", "h1", "h2", "h3", "h4", "h5", "h6",
               "blockquote", "pre", "tr"]


def _html_to_text(html: str) -> str:
    """HTML本文をプレーンテキスト化。ブロック要素のみ改行にする
    （インラインの <strong> 等では改行しない）。"""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for block in soup.find_all(_BLOCK_TAGS):
        block.append("\n")
    text = soup.get_text()
    # 連続する空行を1つに圧縮し、各行を trim
    lines = [ln.strip() for ln in text.splitlines()]
    out: list[str] = []
    for ln in lines:
        if ln or (out and out[-1] != ""):
            out.append(ln)
    return "\n".join(out).strip()


def fetch_entries(feed_cfg: FeedConfig) -> list[Entry]:
    """1つのフィードから Entry のリストを取得する。"""
    parsed = feedparser.parse(_fetch(feed_cfg.url))
    entries: list[Entry] = []
    for e in parsed.entries:
        # content があれば優先、なければ summary
        body_html = ""
        if e.get("content"):
            body_html = e.content[0].get("value", "")
        body_html = body_html or e.get("summary", "")

        entries.append(
            Entry(
                id=_stable_id(e),
                title=e.get("title", "(無題)").strip(),
                link=e.get("link", ""),
                summary=_html_to_text(body_html),
                tags=list(feed_cfg.tags),
            )
        )
    return entries


def fetch_all(feeds: list[FeedConfig]) -> list[Entry]:
    all_entries: list[Entry] = []
    for f in feeds:
        all_entries.extend(fetch_entries(f))
    return all_entries


def fetch_article_text(url: str) -> str:
    """記事URLから本文をプレーンテキストで抽出する。
    取得・抽出に失敗した場合は空文字を返す（呼び出し側でフォールバック）。"""
    if not url:
        return ""
    try:
        import trafilatura  # 遅延import

        html = trafilatura.fetch_url(url)
        if not html:
            # certifi コンテキストで自前取得してリトライ
            raw = _fetch(url)
            html = raw.decode("utf-8", "ignore") if isinstance(raw, bytes) else raw
        text = trafilatura.extract(
            html, include_comments=False, include_tables=False, favor_recall=True
        )
        return text or ""
    except Exception:
        return ""
