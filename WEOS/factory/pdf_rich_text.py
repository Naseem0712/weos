"""Inline rich text helpers for ReportLab canvas PDF (bold + line breaks)."""

from __future__ import annotations

import re
from html import unescape
from typing import Callable

_BOLD_MARKERS = ("**", "__")
_HAS_RICH = re.compile(
    r"\*\*.+?\*\*|__.+?__|<(?:b|strong)\b[^>]*>.*?</(?:b|strong)>",
    re.IGNORECASE | re.DOTALL,
)
_HTML_BREAK = re.compile(r"<\s*br\s*/?\s*>", re.IGNORECASE)
_HTML_BLOCK_END = re.compile(r"</\s*(?:p|div|li|tr|h[1-6])\s*>", re.IGNORECASE)
_HTML_BOLD = re.compile(
    r"<\s*(?:b|strong)\b[^>]*>(.*?)</\s*(?:b|strong)\s*>",
    re.IGNORECASE | re.DOTALL,
)
_STRIP_TAGS = re.compile(r"<[^>]+>")


def has_rich_markers(text: str) -> bool:
    raw = str(text or "")
    if not raw.strip():
        return False
    if _HAS_RICH.search(raw):
        return True
    return bool(_HTML_BOLD.search(raw))


def html_paste_to_markdown(html: str) -> str:
    """Convert clipboard HTML (Word / ChatGPT rich copy) to markdown-like plain text."""
    raw = str(html or "").strip()
    if not raw:
        return ""
    s = raw
    s = _HTML_BREAK.sub("\n", s)
    s = _HTML_BLOCK_END.sub("\n", s)
    s = re.sub(r"<\s*(?:p|div|li|tr|h[1-6])\b[^>]*>", "", s, flags=re.IGNORECASE)
    s = _HTML_BOLD.sub(lambda m: f"**{m.group(1).strip()}**", s)
    s = re.sub(
        r"<\s*(?:i|em)\b[^>]*>(.*?)</\s*(?:i|em)\s*>",
        r"*\1*",
        s,
        flags=re.IGNORECASE | re.DOTALL,
    )
    s = _STRIP_TAGS.sub("", s)
    s = unescape(s)
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _html_to_markers(text: str) -> str:
    s = str(text or "")
    if "<" not in s:
        return s
    s = _HTML_BREAK.sub("\n", s)
    s = _HTML_BLOCK_END.sub("\n", s)
    s = re.sub(r"<\s*(?:p|div|li|tr|h[1-6])\b[^>]*>", "", s, flags=re.IGNORECASE)
    s = _HTML_BOLD.sub(lambda m: f"**{m.group(1)}**", s)
    s = _STRIP_TAGS.sub("", s)
    return unescape(s)


def _parse_spans(text: str) -> list[tuple[str, bool]]:
    """Split text into (fragment, bold) segments."""
    src = _html_to_markers(text)
    spans: list[tuple[str, bool]] = []
    i = 0
    n = len(src)
    while i < n:
        matched = False
        for marker in _BOLD_MARKERS:
            mlen = len(marker)
            if src.startswith(marker, i):
                end = src.find(marker, i + mlen)
                if end != -1:
                    spans.append((src[i + mlen : end], True))
                    i = end + mlen
                    matched = True
                    break
        if matched:
            continue
        nxt = n
        for marker in _BOLD_MARKERS:
            pos = src.find(marker, i)
            if pos != -1:
                nxt = min(nxt, pos)
        chunk = src[i:nxt]
        if chunk:
            spans.append((chunk, False))
        i = nxt if nxt > i else i + 1
    if not spans:
        return [(src, False)]
    return spans


def _word_tokens(spans: list[tuple[str, bool]]) -> list[tuple[str, bool]]:
    tokens: list[tuple[str, bool]] = []
    for frag, bold in spans:
        for m in re.finditer(r"\S+|\s+", frag):
            tokens.append((m.group(), bold))
    return tokens


def _token_width(c, token: str, font_size: float, bold: bool, set_font: Callable) -> float:
    set_font(c, font_size, bold=bold)
    try:
        return float(c.stringWidth(token, c._fontname, font_size))
    except Exception:
        return len(token) * font_size * 0.5


def _wrap_tokens(c, tokens, max_width: float, font_size: float, set_font: Callable) -> list[list[tuple[str, bool]]]:
    lines: list[list[tuple[str, bool]]] = []
    line: list[tuple[str, bool]] = []
    width = 0.0
    for token, bold in tokens:
        tw = _token_width(c, token, font_size, bold, set_font)
        if line and width + tw > max_width and token.strip():
            lines.append(line)
            line = [(token, bold)]
            width = tw
            continue
        if not line and tw > max_width and token.strip():
            chunk = ""
            for ch in token:
                t2 = chunk + ch
                cw = _token_width(c, t2, font_size, bold, set_font)
                if chunk and cw > max_width:
                    lines.append([(chunk, bold)])
                    chunk = ch
                else:
                    chunk = t2
            if chunk:
                line = [(chunk, bold)]
                width = _token_width(c, chunk, font_size, bold, set_font)
            continue
        line.append((token, bold))
        width += tw
    if line:
        lines.append(line)
    return lines


def _draw_line(c, x: float, y: float, parts: list[tuple[str, bool]], font_size: float, set_font: Callable) -> None:
    cx = x
    for text, bold in parts:
        if not text:
            continue
        set_font(c, font_size, bold=bold)
        c.drawString(cx, y, text)
        try:
            cx += float(c.stringWidth(text, c._fontname, font_size))
        except Exception:
            cx += len(text) * font_size * 0.5


def _flow_plain(
    c,
    text: str,
    *,
    x: float,
    y: float,
    max_width: float,
    font_size: float,
    line_h: float,
    bottom: float,
    set_font: Callable,
    on_new_page: Callable[[], float],
    para_gap: float = 4.0,
    bold: bool = False,
) -> float:
    for para in str(text or "").split("\n"):
        words = para.split()
        if not words:
            y -= para_gap
            if y < bottom:
                y = on_new_page()
            continue
        line = ""
        set_font(c, font_size, bold=bold)
        for word in words:
            trial = (line + " " + word).strip()
            try:
                too_wide = c.stringWidth(trial, c._fontname, font_size) > max_width
            except Exception:
                too_wide = len(trial) * (font_size * 0.5) > max_width
            if too_wide and line:
                if y < bottom:
                    y = on_new_page()
                    set_font(c, font_size, bold=bold)
                c.drawString(x, y, line)
                y -= line_h
                line = word
            else:
                line = trial
        if line:
            if y < bottom:
                y = on_new_page()
                set_font(c, font_size, bold=bold)
            c.drawString(x, y, line)
            y -= line_h
        y -= para_gap
    return y


def flow_rich_paragraphs(
    c,
    text: str,
    *,
    x: float,
    y: float,
    max_width: float,
    font_size: float,
    line_h: float,
    bottom: float,
    set_font: Callable,
    on_new_page: Callable[[], float],
    para_gap: float = 4.0,
    bold: bool = False,
) -> float:
    """Draw wrapping paragraphs with inline **bold** / HTML bold markers."""
    raw = str(text or "")
    if not has_rich_markers(raw):
        return _flow_plain(
            c,
            raw,
            x=x,
            y=y,
            max_width=max_width,
            font_size=font_size,
            line_h=line_h,
            bottom=bottom,
            set_font=set_font,
            on_new_page=on_new_page,
            para_gap=para_gap,
            bold=bold,
        )

    for para in raw.split("\n"):
        tokens = _word_tokens(_parse_spans(para))
        if not tokens:
            y -= para_gap
            if y < bottom:
                y = on_new_page()
            continue
        for line_parts in _wrap_tokens(c, tokens, max_width, font_size, set_font):
            if y < bottom:
                y = on_new_page()
            _draw_line(c, x, y, line_parts, font_size, set_font)
            y -= line_h
        y -= para_gap
    return y
