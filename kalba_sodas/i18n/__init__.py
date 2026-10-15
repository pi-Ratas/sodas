"""The interface in several languages.

The program is written in Lithuanian; a translation is a dictionary from the Lithuanian text to the other language's.
``raktai.tsv`` numbers every Lithuanian text of the interface (``istraukti.py`` fills it), ``<kalba>.tsv`` gives the
translation of each number. The browser gets one language's dictionary as a script (``/sodas/i18n/<kalba>.js``) and
``static/i18n.js`` translates the page with it – the texts written in the HTML, those the scripts put on the page later,
the server's messages – so the rest of the code keeps its Lithuanian texts as they are.

A text with ``{0}``, ``{1}`` … is a pattern: the parts the program fills in (a number, a name) are kept as they are.
A text not translated yet stays Lithuanian.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
# code → (its own name, the locale for dates and numbers)
LANGS: dict[str, tuple[str, str]] = {
    "lt": ("Lietuvių", "lt-LT"),
    "en": ("English", "en-GB"),
    "lv": ("Latviešu", "lv-LV"),
    "pl": ("Polski", "pl-PL"),
    "uk": ("Українська", "uk-UA"),
    "be": ("Беларуская", "be-BY"),
    "ru": ("Русский", "ru-RU"),
    "de": ("Deutsch", "de-DE"),
    "fr": ("Français", "fr-FR"),
    "es": ("Español", "es-ES"),
    "it": ("Italiano", "it-IT"),
    "pt": ("Português", "pt-BR"),
    "ar": ("العربية", "ar-u-nu-latn"),
    "ja": ("日本語", "ja-JP"),
    "zh": ("中文（简体）", "zh-CN"),
}
DEFAULT = "en"
_cache: dict[str, tuple[float, str]] = {}
_lock = threading.Lock()


def read_tsv(path: Path) -> dict[str, str]:
    """number → text; lines starting with # are comments."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "\t" not in line:
            continue
        k, v = line.split("\t", 1)
        if v.strip():
            out[k.strip()] = v.strip()
    return out


def dictionary(lang: str) -> dict[str, str]:
    """Lithuanian text → its translation in ``lang`` (empty for Lithuanian itself)."""
    if lang not in LANGS or lang == "lt":
        return {}
    keys = read_tsv(HERE / "raktai.tsv")
    tr = read_tsv(HERE / f"{lang}.tsv")
    return {keys[k]: v for k, v in tr.items() if k in keys}


def script(lang: str) -> str:
    """The browser's dictionary of one language (kept until a .tsv file changes)."""
    if lang not in LANGS:
        lang = DEFAULT
    files = [HERE / "raktai.tsv", HERE / f"{lang}.tsv"]
    stamp = sum(f.stat().st_mtime for f in files if f.exists())
    with _lock:
        hit = _cache.get(lang)
        if hit and hit[0] == stamp:
            return hit[1]
    body = "window.SODAS_I18N = " + json.dumps({"lang": lang, "dict": dictionary(lang)}, ensure_ascii=False, separators=(",", ":")) + ";\n"
    with _lock:
        _cache[lang] = (stamp, body)
    return body


def languages() -> list[dict[str, str]]:
    return [{"code": k, "name": n, "locale": loc} for k, (n, loc) in LANGS.items()]
