"""Article text for the LLM, read again from the saved LKEŽDB page HTML.

The stored ``straipsniai.istrauka`` lost the spaces around italic words („kalbosesmi,esti“). The page HTML
(``puslapiai.LKEZDB_atsakymas``) still has them, and its italics (``<em>``) mark the cited language forms, which
are kept as ``⟨…⟩`` (not ``*``: an asterisk already means a reconstruction, ``*⟨esmei⟩``).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

OPEN, CLOSE = "⟨", "⟩"


@dataclass
class Block:
    title: str = ""
    meaning: str = ""
    text: str = ""
    cite: str = ""
    links: list[str] = field(default_factory=list)


class _Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[Block] = []
        self.cur: Block | None = None
        self.field: str | None = None
        self.buf: list[str] = []
        self.in_link = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class") or ""
        if tag == "dl" and "word" in cls.split():
            self.cur = Block()
        elif tag == "dd" and self.cur is not None:
            self.field = cls.split()[0] if cls else None
            self.buf = []
        elif tag == "em" and self.field == "description":
            self.buf.append(OPEN)
        elif tag == "cite" and self.cur is not None:
            self.cur.cite = a.get("title") or ""
        elif tag == "a" and self.field == "description":
            href = a.get("href") or ""
            m = re.search(r"[?&]w=([^&]+)", href)
            if m:
                from urllib.parse import unquote
                self.cur.links.append(unquote(m.group(1)))

    def handle_endtag(self, tag):
        if tag == "em" and self.field == "description":
            self.buf.append(CLOSE)
        elif tag == "dd" and self.cur is not None and self.field:
            text = clean("".join(self.buf))
            if self.field == "title":
                self.cur.title = text
            elif self.field == "meaning":
                self.cur.meaning = text
            elif self.field == "description":
                self.cur.text = text
            self.field = None
        elif tag == "dl" and self.cur is not None:
            self.blocks.append(self.cur)
            self.cur = None

    def handle_data(self, data):
        if self.field:
            self.buf.append(data)


def clean(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = text.replace(f"{OPEN}{CLOSE}", "")
    # ⟨esmi⟩ ,⟨esti⟩ → ⟨esmi⟩, ⟨esti⟩ is left as written; only whitespace inside the markers is trimmed
    return re.sub(rf"{OPEN}\s+", OPEN, re.sub(rf"\s+{CLOSE}", CLOSE, text))


def parse_page(html: str | None) -> list[Block]:
    if not html:
        return []
    p = _Parser()
    p.feed(html)
    return p.blocks


def _squash(text: str | None) -> str:
    return re.sub(r"[\s⟨⟩]+", "", text or "")


def article_texts(html: str | None, articles: list[dict]) -> dict[str, str]:
    """GUID → text with italics, matching each stored article to its HTML block by its letters (no spaces)."""
    blocks = parse_page(html)
    by_letters: dict[str, list[Block]] = {}
    for b in blocks:
        by_letters.setdefault(_squash(b.text), []).append(b)
    out = {}
    for a in articles:
        cands = by_letters.get(_squash(a.get("istrauka")), [])
        if cands:
            out[a["GUID"]] = cands.pop(0).text if len(cands) > 1 else cands[0].text
        else:
            out[a["GUID"]] = a.get("istrauka") or ""
    return out


def plain(text: str) -> str:
    return text.replace(OPEN, "").replace(CLOSE, "")


def cross_reference(text: str) -> str | None:
    """„žr. eglė“: the article only points to another entry."""
    m = re.fullmatch(r"(?i)\s*žr\.?\s*([^\s,.;:!?()\[\]{}][^,.;:!?()\[\]{}]*)\s*\.?\s*", plain(text or ""))
    return m.group(1).strip() if m else None
