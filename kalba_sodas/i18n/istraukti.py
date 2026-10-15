"""Collects the interface's Lithuanian texts into ``raktai.tsv`` and tells which translations are missing.

    python -m kalba_sodas.i18n.istraukti            # new texts get new numbers; a report of what is not translated
    python -m kalba_sodas.i18n.istraukti --trukstami en   # the untranslated texts of one language (number, text)

Sources: the pages and scripts in ``static/`` (and the importer's page), and the messages of the server's Python code
(errors shown to the user, Vaiva's study descriptions). A text with values put in it becomes a pattern: in
``Ištrinti {0} mazgų?`` the ``{0}`` stands for whatever the program puts there; a translation keeps the same ``{n}``.
Texts that are gone from the code stay in the file (marked by nothing): ``--valyti`` drops them.
"""
from __future__ import annotations

import ast
import html
import re
import sys
from pathlib import Path

from . import HERE, LANGS, read_tsv

ROOT = HERE.parent
JS_FILES = sorted(p for p in (ROOT / "static").glob("*.js") if p.name not in ("leaflet.js", "i18n.js"))
HTML_FILES = sorted((ROOT / "static").glob("*.html")) + [ROOT.parent / "kalba_import" / "ui" / "index.html"]
PY_FILES = ([p for p in ROOT.glob("*.py") if p.name not in ("cli.py", "db.py", "models.py", "__init__.py", "bibliografija.py")]
            + sorted((ROOT / "vaiva").rglob("*.py"))
            + [ROOT.parent / "kalba_lkezdb" / n for n in ("service.py", "store.py")])
ATTRS = ("title", "placeholder", "aria-label", "alt", "data-tip", "label")
SHOWN_ARGS = {"title", "label", "summary", "help", "hint"}      # keyword arguments of the Vaiva parts shown on the page
NOT_TEXT = {"Enter", "Esc", "Escape", "Delete", "Home", "Digit1", "DOMContentLoaded", "Content-Type", "add remove", "Form", "Concept",
            "Entry", "Dataset", "Aa", "Ctrl+F", "Ctrl+J", "Ctrl+Alt+1", "Ctrl+Shift+1", "Gravatar", "Notification", "Neo4j", "LKEŽDB",
            "Vaiva", "Sodas", "Povai", "Languoid", "Lexeme", "Sense", "Segments", "Phonemic_Segments", "node, edge",
            "X-Filename", "Backspace", "Ctrl+D", "block fruit", "input, textarea, select"}
# short lowercase words the rules below would take for identifiers
ALWAYS_TEXT = {"autoritetas", "remiasi: {0}", "visi"}
LT = re.compile(r"[ąčęėįšųūžĄČĘĖĮŠŲŪŽ„“–…]")
MARK = "\x00"


def natural(text: str) -> bool:
    """Is it a text for people (not a class name, a selector, a path, a piece of code)?"""
    if text in ALWAYS_TEXT:
        return True
    t = re.sub(r"\{\d+\}", "", text).strip()
    if not re.search(r"[A-Za-zĄ-ž]{2}", t):
        return False
    if re.search(r"=>|\bfunction\b|\bconst\b|\breturn\b|;\s*$|^[#\[/]|^\.[A-Za-z_-]|^https?:|\(\)|\$\{|&&|\|\|", t):
        return False
    if re.fullmatch(r"[a-z0-9_.:/#\-]+", t) and not LT.search(t):
        return False                       # an identifier, a class, a path
    if re.fullmatch(r"[a-z0-9_\- ]+", t) and ("-" in t or "_" in t) and not LT.search(t):
        return False                       # "kb-avatar big"
    if re.fullmatch(r"[A-ZĄ-Ž0-9_]+", t) or re.search(r"\w\[|\[\w|^(virtual|pill|toast|premap|mapRel|use) |^(min|translate)\(|\.md$|@\w+\.\w", t):
        return False                       # a relationship type
    if re.search(r"^[a-z-]+\s*:\s*[^ ]", t) and ";" in t:
        return False                       # inline css
    if re.search(r'="|\(in srgb|^hsl\(|\[type|^<|^[A-Z][a-z]+\||^\{0\}px', text) or t in NOT_TEXT:
        return False                       # markup, css, a selector, a key name
    if LT.search(t):
        return True
    return bool(re.match(r"^[A-ZĄ-Ž]", t) and not re.fullmatch(r"[A-Z][a-z]+[A-Z]\w*", t)) or " " in t


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def placeholders(seg: str) -> str:
    """\x00n\x00 markers → {0}, {1}, … in the order they appear."""
    n = iter(range(100))
    return re.sub(MARK + r"\d+" + MARK, lambda m: "{%d}" % next(n), seg)


def from_markup(s: str, out: set[str]) -> None:
    """Texts of a piece of HTML (the markers stand for ${…}): attribute values and the text between tags."""
    for m in re.finditer(r"\b(%s)\s*=\s*\"([^\"]*)\"" % "|".join(ATTRS), s):
        add(placeholders(m.group(2)), out)
    s = re.sub(r"<(script|style)\b.*?</\1>", " ", s, flags=re.S)
    s = re.sub(r"<!--.*?-->", " ", s, flags=re.S)
    for seg in re.split(r"<[^<>]*>|<[^<>]*$|^[^<>]*>", s):
        add(placeholders(seg), out)


def add(text: str, out: set[str]) -> None:
    t = renumber(clean(text))
    if natural(t) and len(t) < 600:
        out.add(t)


def add_word(text: str, out: set[str]) -> None:
    """A text known to be shown, even a single lowercase word."""
    t = clean(text)
    if re.search(r"[A-Za-zĄ-ž]{2}", t):
        out.add(renumber(t))


def renumber(t: str) -> str:
    n = iter(range(100))
    return re.sub(r"\{\d+\}", lambda m: "{%d}" % next(n), t)


# ---------------------------------------------------------------- JavaScript
def js_strings(src: str) -> list[tuple[str, bool]]:
    """String literals of a script: (text, is template). In a template ``${…}`` becomes a marker."""
    out: list[tuple[str, bool]] = []
    n = len(src)

    def template(i: int) -> int:
        """From after the opening backtick; returns the index after the closing one."""
        buf, k = [], 0
        while i < n:
            c = src[i]
            if c == "\\":
                buf.append(src[i + 1] if i + 1 < n else ""); i += 2; continue
            if c == "`":
                out.append(("".join(buf), True))
                return i + 1
            if c == "$" and src[i + 1:i + 2] == "{":
                i = code(i + 2, True)
                buf.append(f"{MARK}{k}{MARK}"); k += 1
                continue
            buf.append(c); i += 1
        out.append(("".join(buf), True))
        return i

    def code(i: int, inside: bool) -> int:
        """Script code from ``i``; ``inside`` a ${…}: returns after its closing brace."""
        depth, prev = 0, ""
        while i < n:
            c = src[i]
            if c in " \t\r\n":
                i += 1; continue
            if src.startswith("//", i):
                i = src.find("\n", i); i = n if i < 0 else i; continue
            if src.startswith("/*", i):
                i = src.find("*/", i + 2); i = n if i < 0 else i + 2; continue
            if c in "'\"":
                j = i + 1
                while j < n and src[j] != c and src[j] != "\n":
                    j += 2 if src[j] == "\\" else 1
                raw = src[i + 1:j]
                out.append((re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), raw), False))
                i, prev = j + 1, "s"; continue
            if c == "`":
                i, prev = template(i + 1), "s"; continue
            if c == "/" and prev in ("", "op"):
                j, cls = i + 1, False
                while j < n and src[j] != "\n":
                    if src[j] == "\\":
                        j += 2; continue
                    if src[j] == "[":
                        cls = True
                    elif src[j] == "]":
                        cls = False
                    elif src[j] == "/" and not cls:
                        break
                    j += 1
                i, prev = j + 1, "s"; continue
            if c.isalnum() or c in "_$":
                j = i
                while j < n and (src[j].isalnum() or src[j] in "_$"):
                    j += 1
                word = src[i:j]
                prev = "op" if word in ("return", "typeof", "case", "in", "of", "void", "delete", "throw", "new") else "s"
                i = j; continue
            if c == "{":
                depth += 1
            elif c == "}":
                if inside and depth == 0:
                    return i + 1
                depth -= 1
            prev = "s" if c in ")]" else "op"
            i += 1
        return i

    code(0, False)
    return out


def from_js(src: str, out: set[str]) -> None:
    for text, is_template in js_strings(src):
        if "<" in text and re.search(r"<[a-zA-Z/!]", text):
            from_markup(text, out)
        else:
            add(placeholders(text) if is_template else text, out)


# ---------------------------------------------------------------- Python
def from_py(src: str, out: set[str], parts: bool = False) -> None:
    """``parts``: a module of Vaiva's workshop – also the names of options ``("id", "name")``, of the data types and of
    the attributes, which are single words without Lithuanian letters."""
    tree = ast.parse(src)
    if parts:
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):          # {"title": …, "summary": …} of the ready setups, {"l": …} of a tile
                for k, v in zip(node.keys, node.values):
                    if isinstance(k, ast.Constant) and k.value in SHOWN_ARGS | {"l"} and isinstance(v, ast.Constant) \
                            and isinstance(v.value, str):
                        add_word(v.value, out)
            if isinstance(node, ast.List):          # options: [("id", "name"), …]
                for e in node.elts:
                    if isinstance(e, ast.Tuple) and len(e.elts) == 2 and all(isinstance(x, ast.Constant) and isinstance(x.value, str)
                                                                             for x in e.elts) and re.fullmatch(r"[a-z0-9_]+", e.elts[0].value):
                        add_word(e.elts[1].value, out)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None and any(
                    getattr(t, "id", "") in ("TYPES", "ATTR_LABELS", "ATTR_NAMES", "GROUPS", "WORDS")
                    for t in (node.targets if isinstance(node, ast.Assign) else [node.target])):
                for c in ast.walk(node.value):
                    if isinstance(c, ast.Constant) and isinstance(c.value, str) and not (
                            isinstance(node.value, ast.Dict) and any(c is k for k in node.value.keys)):
                        add_word(c.value, out)
    docs = {id(node.body[0].value) for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)) and node.body
            and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)}
    inner = {id(v) for node in ast.walk(tree) if isinstance(node, ast.JoinedStr) for v in node.values}
    for node in ast.walk(tree):
        if id(node) in docs or id(node) in inner:
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and LT.search(node.value):
            add(node.value, out)
        elif isinstance(node, ast.keyword) and node.arg in SHOWN_ARGS and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            add(node.value.value, out)              # Vaiva's parts: titles and labels without Lithuanian letters
        elif isinstance(node, ast.Call) and getattr(node.func, "id", "") in ("Param", "Port") and len(node.args) > 1 \
                and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str) \
                and getattr(node.func, "id", "") == "Param":
            add(node.args[1].value, out)
        elif isinstance(node, ast.JoinedStr):
            parts, k = [], 0
            for v in node.values:
                if isinstance(v, ast.Constant):
                    parts.append(str(v.value))
                else:
                    parts.append(f"{MARK}{k}{MARK}"); k += 1
            text = "".join(parts)
            if LT.search(text):
                add(placeholders(text), out)


def collect() -> set[str]:
    out: set[str] = set()
    for p in HTML_FILES:
        src = p.read_text(encoding="utf-8")
        from_markup(src, out)
        for m in re.finditer(r"<script>(.*?)</script>", src, flags=re.S):
            from_js(m.group(1), out)
        m = re.search(r"<title>(.*?)</title>", src)
        if m:
            add(m.group(1), out)
    for p in JS_FILES:
        from_js(p.read_text(encoding="utf-8"), out)
    for p in PY_FILES:
        if p.exists():
            from_py(p.read_text(encoding="utf-8"), out, parts="dirbtuves" in p.parts)
    return out


def main(argv: list[str]) -> int:
    keys = read_tsv(HERE / "raktai.tsv")
    found = collect()
    have = set(keys.values())
    nxt = max(map(int, keys), default=0) + 1
    new = sorted(found - have, key=lambda s: s.lower())
    if "--valyti" in argv:
        keys = {k: v for k, v in keys.items() if v in found}
    for t in new:
        keys[str(nxt)] = t
        nxt += 1
    with open(HERE / "raktai.tsv", "w", encoding="utf-8") as f:
        f.write("# Sodo sąsajos tekstai lietuviškai (numeris<TAB>tekstas). Pildo: python -m kalba_sodas.i18n.istraukti\n")
        for k, v in sorted(keys.items(), key=lambda kv: int(kv[0])):
            f.write(f"{k}\t{v}\n")
    if "--trukstami" in argv:
        lang = argv[argv.index("--trukstami") + 1]
        done = read_tsv(HERE / f"{lang}.tsv")
        for k, v in sorted(keys.items(), key=lambda kv: int(kv[0])):
            if k not in done and v in found:
                print(f"{k}\t{v}")
        return 0
    print(f"tekstų: {len(found)}, naujų: {len(new)}, nebenaudojamų: {len(set(keys.values()) - found)}")
    for lang in LANGS:
        if lang == "lt":
            continue
        done = read_tsv(HERE / f"{lang}.tsv")
        missing = sum(1 for k, v in keys.items() if v in found and k not in done)
        print(f"  {lang}: neišversta {missing}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
