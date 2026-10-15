"""Analysis segments of a form (Tyrimo_mintys.md §15): the source layers are never overwritten.

Order of preference, the first one present wins:

1. ``segments``           – the form's CLDF ``Segments`` (``Form.segments`` in Neo4j);
2. ``phonemic_segments``  – IE-CoR ``Phonemic_Segments`` (kept in the form's ``SourceRecord.raw_json``);
3. ``orthography``        – the form segmented with the dataset's ``etc/orthography.tsv`` profile
                            (greedy longest match, as the ``segments`` package does).

A form whose every variant has a character the profile does not know is not segmented: it is reported as
excluded for missing data instead of being guessed.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# segment tokens that are not sounds: morpheme / word boundaries, empty and stress / syllable marks
NON_SOUNDS = {"", "+", "_", "#", "-", "Ø", "∅", "NULL", ".", "ˈ", "ˌ", "|"}
STRESS = "ˈˌ"
VARIANT_SPLIT = re.compile(r"\s*[,/;~]\s*")

SOURCE_LABELS = {
    "segments": "IE-CoR / CLDF Segments",
    "phonemic_segments": "IE-CoR Phonemic_Segments",
    "orthography": "išvesta iš etc/orthography.tsv",
}


def clean_tokens(tokens: list[str]) -> list[str]:
    """Sound tokens only; ``a/b`` (source/BIPA notation of Lexibank) keeps the BIPA side."""
    out = []
    for tok in tokens:
        tok = str(tok).strip()
        if "/" in tok and tok != "/":
            tok = tok.split("/")[-1]
        tok = tok.strip(STRESS)
        if tok in NON_SOUNDS:
            continue
        out.append(unicodedata.normalize("NFC", tok))
    return out


def split_segments(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return clean_tokens([str(v) for v in value])
    return clean_tokens(str(value).split())


class OrthographyProfile:
    """``Grapheme`` → ``IPA`` table of a CLDF dataset (``etc/orthography.tsv``)."""

    def __init__(self, path: Path):
        self.path = path
        self.map: dict[str, str] = {}
        with path.open(encoding="utf-8-sig", newline="") as fh:
            reader = csv.reader(fh, delimiter="\t", quoting=csv.QUOTE_NONE)
            header = next(reader, [])
            out_col = header.index("IPA") if "IPA" in header else 1
            for row in reader:
                if len(row) > out_col and row[0]:
                    self.map[unicodedata.normalize("NFD", row[0])] = row[out_col].strip()
        self.longest = max((len(k) for k in self.map), default=1)

    def segment(self, text: str) -> tuple[list[str], list[str]]:
        """(sound tokens, characters the profile does not know)."""
        s = unicodedata.normalize("NFD", text.strip())
        i, out, unknown = 0, [], []
        while i < len(s):
            if s[i].isspace():
                i += 1
                continue
            for size in range(min(self.longest, len(s) - i), 0, -1):
                part = s[i:i + size]
                hit = self.map.get(part) if part in self.map else self.map.get(part.lower())
                if hit is not None:
                    out.extend(hit.split())
                    i += size
                    break
            else:
                unknown.append(s[i])
                i += 1
        return clean_tokens(out), unknown


_profiles: dict[Path, OrthographyProfile | None] = {}


def profile_for(dataset_path: Path | None) -> OrthographyProfile | None:
    if dataset_path is None:
        return None
    path = dataset_path / "etc" / "orthography.tsv"
    if path not in _profiles:
        _profiles[path] = OrthographyProfile(path) if path.is_file() else None
    return _profiles[path]


@dataclass
class Segmented:
    variants: list[list[str]] = field(default_factory=list)   # one segment list per written variant
    source: str | None = None                                 # key of SOURCE_LABELS
    reason: str | None = None                                  # why the form is excluded
    detail: str | None = None
    reconstructed: bool = False


def _char_names(chars: list[str]) -> str:
    seen = []
    for c in chars:
        label = f"„{c}“ ({unicodedata.name(c, f'U+{ord(c):04X}').lower()})" if unicodedata.combining(c) or not c.isprintable() \
            else f"„{c}“"
        if label not in seen:
            seen.append(label)
    return ", ".join(seen)


def analysis_segments(form_segments: Any, raw: dict[str, Any], written: str | None,
                      profile: OrthographyProfile | None, include_reconstructed: bool = False) -> Segmented:
    written = (written or "").strip()
    reconstructed = written.startswith("*")
    if reconstructed and not include_reconstructed:
        return Segmented(reason="rekonstruota forma", reconstructed=True,
                         detail="Žvaigždute pažymėta forma nėra tiesiogiai paliudyta; ji tiriama tik pažymėjus „įtraukti rekonstruotas formas“.")
    for source, value in (("segments", form_segments), ("phonemic_segments", raw.get("Phonemic_Segments"))):
        segs = split_segments(value)
        if segs:
            return Segmented([segs], source, reconstructed=reconstructed)
    if not written:
        return Segmented(reason="nėra formos teksto", detail="Forma neturi nei segmentų, nei užrašytos formos.")
    if profile is None:
        return Segmented(reason="trūksta segmentacijos",
                         detail="Forma neturi Segments ar Phonemic_Segments, o jos duomenynas neturi etc/orthography.tsv.")
    variants, failed = [], []
    for variant in (v for v in VARIANT_SPLIT.split(written) if v.strip()):
        segs, unknown = profile.segment(variant.lstrip("*"))
        if unknown or not segs:
            failed.append((variant, unknown))
        else:
            variants.append(segs)
    if not variants:
        chars = [c for _, unknown in failed for c in unknown]
        return Segmented(reason="trūksta segmentacijos",
                         detail=f"etc/orthography.tsv nežino ženklų {_char_names(chars)}; tarimo neišradinėjame." if chars
                         else "etc/orthography.tsv nepateikė nė vieno garso.")
    return Segmented(variants, "orthography", reconstructed=reconstructed,
                     detail=(f"Neįtraukti variantai: {', '.join(v for v, _ in failed)}." if failed else None))
