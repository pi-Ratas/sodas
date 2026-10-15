"""Segment → CLTS sound → features, and a feature-weighted edit distance between segment sequences.

Sound lookup (Tyrimo_mintys.md §10): BIPA first (``Sound.symbol`` is the BIPA grapheme). Otherwise another CLTS
transcription system or transcription data set is used only when every grapheme with that symbol represents
one and the same sound; sound-class systems (ASJP, SCA, Dolgopolsky …) are never used, their symbols stand for
many sounds. What is still unknown is tried without its diacritics, one at a time from the right (an
approximation, reported as such); what remains is compared only as the same / a different symbol.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Any

INDEL = 0.5            # inserting or deleting one sound; a substitution costs 0 … 1
VOWELISH = {"vowel", "diphthong"}


@dataclass
class SoundInfo:
    symbol: str
    via: str                      # bipa | system | approx | unknown
    sound_key: str | None = None
    name: str | None = None
    sound_type: str | None = None
    features: dict[str, str] = field(default_factory=dict)
    systems: list[str] = field(default_factory=list)
    base: str | None = None       # the symbol really found, for approximations

    def out(self) -> dict[str, Any]:
        return {"symbol": self.symbol, "via": self.via, "sound_key": self.sound_key, "name": self.name,
                "type": self.sound_type, "systems": self.systems[:6], "base": self.base}


ACCENTS = {"\u0300", "\u0301", "\u0302", "\u0304", "\u0306", "\u030c", "\u030b", "\u030f", "\u0311"}


def _strip_steps(symbol: str) -> list[str]:
    """Simpler symbols to try, closest first: ``òː`` → ``oː`` (tone / stress accents go first, length stays),
    then other diacritics and modifier letters one at a time from the right (``a̠ˤ`` → ``a̠`` → ``a``)."""
    s = unicodedata.normalize("NFD", symbol)
    steps = []
    no_accents = "".join(c for i, c in enumerate(s) if i == 0 or c not in ACCENTS)
    if no_accents != s:
        steps.append(unicodedata.normalize("NFC", no_accents))
        s = no_accents
    while len(s) > 1:
        idx = next((i for i in range(len(s) - 1, 0, -1)
                    if unicodedata.combining(s[i]) or unicodedata.category(s[i]) == "Lm" or s[i] in "ːˑ"), None)
        if idx is None:
            break
        s = s[:idx] + s[idx + 1:]
        steps.append(unicodedata.normalize("NFC", s))
    return steps


class SoundTable:
    def __init__(self, read):
        self.read = read
        self.sounds: dict[str, SoundInfo] = {}

    def _bipa(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        if not symbols:
            return {}
        rows = self.read("MATCH (s:Sound) WHERE s.symbol IN $syms RETURN s.symbol AS sym, s.key AS key, s.name AS name, "
                         "s.sound_type AS type", syms=symbols)
        return {r["sym"]: dict(r) for r in rows}

    def _systems(self, symbols: list[str]) -> dict[str, dict[str, Any]]:
        if not symbols:
            return {}
        rows = self.read(
            "MATCH (t:TranscriptionSystem) WHERE t.kind <> 'sound classes' WITH collect(t.name) AS systems "
            "MATCH (g:Grapheme) WHERE g.symbol IN $syms AND g.system IN systems "
            "MATCH (g)-[:REPRESENTS]->(s:Sound) "
            "RETURN g.symbol AS sym, collect(DISTINCT s.key) AS keys, collect(DISTINCT s.name) AS names, "
            "collect(DISTINCT s.sound_type) AS types, collect(DISTINCT g.system) AS systems", syms=symbols)
        return {r["sym"]: {"key": r["keys"][0], "name": r["names"][0], "type": r["types"][0], "systems": sorted(r["systems"])}
                for r in rows if len(r["keys"]) == 1}

    def resolve(self, symbols: set[str]) -> None:
        todo = sorted(s for s in symbols if s not in self.sounds)
        found = self._bipa(todo)
        for sym, r in found.items():
            self.sounds[sym] = SoundInfo(sym, "bipa", r["key"], r["name"], r["type"])
        rest = [s for s in todo if s not in found]
        other = self._systems(rest)
        for sym, r in other.items():
            self.sounds[sym] = SoundInfo(sym, "system", r["key"], r["name"], r["type"], systems=r["systems"])
        rest = [s for s in rest if s not in other]
        steps = {s: _strip_steps(s) for s in rest}
        approx = self._bipa(sorted({x for st in steps.values() for x in st}))
        for sym in rest:
            base = next((x for x in steps[sym] if x in approx), None)
            if base:
                r = approx[base]
                self.sounds[sym] = SoundInfo(sym, "approx", r["key"], r["name"], r["type"], base=base)
            else:
                self.sounds[sym] = SoundInfo(sym, "unknown")
        keys = sorted({i.sound_key for i in self.sounds.values() if i.sound_key and not i.features})
        if keys:
            rows = self.read("MATCH (s:Sound) WHERE s.key IN $keys "
                             "MATCH (s)-[:HAS_FEATURE_VALUE]->(v:FeatureValue)-[:VALUE_OF]->(f:Feature) "
                             "RETURN s.key AS key, collect([f.feature, v.raw_value]) AS fv", keys=keys)
            feats = {r["key"]: {f: v for f, v in r["fv"]} for r in rows}
            for info in self.sounds.values():
                if info.sound_key in feats:
                    info.features = feats[info.sound_key]

    def distance(self, a: str, b: str) -> float:
        """0 … 1: the share of feature categories in which two sounds differ."""
        if a == b:
            return 0.0
        x, y = self.sounds.get(a), self.sounds.get(b)
        if x is None or y is None or not x.sound_key or not y.sound_key:
            return 1.0
        if x.sound_key == y.sound_key:
            return 0.0
        if x.sound_type != y.sound_type:
            return 0.5 if {x.sound_type, y.sound_type} <= VOWELISH else 1.0
        cats = set(x.features) | set(y.features)
        if not cats:
            return 1.0
        return sum(1 for c in cats if x.features.get(c) != y.features.get(c)) / len(cats)


def edit_distance(a: list[int], b: list[int], sub: list[list[float]]) -> float:
    """Weighted Levenshtein over sound indices, normalised by the longer sequence (0 … 1)."""
    if not a or not b:
        return 1.0
    prev = [j * INDEL for j in range(len(b) + 1)]
    for i, x in enumerate(a, 1):
        row = sub[x]
        cur = [i * INDEL]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + INDEL, cur[j - 1] + INDEL, prev[j - 1] + row[y]))
        prev = cur
    return prev[-1] / max(len(a), len(b))
