"""The bibliography of a piece of work: the environment SODAS itself and every dataset the work used (``sekimas``).

The entry of SODAS comes from ``CITATION.cff`` (Citation File Format) next to datasets.yaml or the program; until there
is one, a trial entry (``TRIAL_CFF``: made-up DOI and repository) is given and marked as such. Datasets are cited as
their authors ask (their ``.zenodo.json``, ``metadata.json``, README): ``CATALOGUE``. A dataset not in the catalogue is
cited from its folder's ``.zenodo.json`` / ``metadata.json`` or, failing that, by its name.

Formats: BibTeX, BibLaTeX, RIS, CSL-JSON (Zotero, Mendeley) and plain text (APA style).
"""
from __future__ import annotations

import copy
import html
import json
import re
import threading
from datetime import date
from pathlib import Path
from typing import Any

MPI_EVA = ("Max Planck Institute for Evolutionary Anthropology", "Leipzig")


def P(family: str, given: str = "") -> dict[str, str]:
    return {"family": family, "given": given}


# Datasets as their authors ask to cite them. ``year``/``version``: of the release the citation names (a newer
# release found on this computer gives its own version and year).
CATALOGUE: dict[str, dict[str, Any]] = {
    "glottolog": {"kind": "dataset", "title": "Glottolog",
                  "authors": [P("Hammarström", "Harald"), P("Forkel", "Robert"), P("Haspelmath", "Martin"), P("Bank", "Sebastian")],
                  "year": 2026, "version": "v5.3", "publisher": MPI_EVA, "url": "https://glottolog.org",
                  "doi": "10.5281/zenodo.596479", "repository": "https://github.com/glottolog/glottolog", "license": "CC-BY-4.0"},
    "concepticon": {"kind": "dataset", "title": "Concepticon: A Resource for the Linking of Concept Lists", "editors": True,
                    "authors": [P("List", "Johann Mattis"), P("Tjuka", "Annika"), P("Blum", "Frederic"), P("Kučerová", "Alžběta"),
                                P("Ugarte", "Carlos Barrientos"), P("Rzymski", "Christoph"), P("Greenhill", "Simon J."), P("Forkel", "Robert")],
                    "year": 2025, "version": "v3.4.0", "publisher": MPI_EVA, "url": "https://concepticon.clld.org",
                    "repository": "https://github.com/concepticon/concepticon-data", "license": "CC-BY-4.0"},
    "clts": {"kind": "dataset", "title": "CLTS: Cross-Linguistic Transcription Systems",
             "authors": [P("List", "Johann-Mattis"), P("Anderson", "Cormac"), P("Tresoldi", "Tiago"), P("Rzymski", "Christoph"),
                         P("Forkel", "Robert")],
             "year": 2024, "version": "v2.3.0", "publisher": MPI_EVA, "url": "https://clts.clld.org", "doi": "10.5281/zenodo.3515744",
             "repository": "https://github.com/cldf-clts/clts", "license": "CC-BY-4.0"},
    "iecor": {"kind": "dataset", "title": "Indo-European Cognate Relationships database (IE-CoR)",
              "authors": [P("Heggarty", "Paul"), P("Anderson", "Cormac"), P("Scarborough", "Matthew")],
              "year": 2024, "version": "v1.2", "publisher": MPI_EVA, "url": "https://iecor.clld.org",
              "repository": "https://github.com/lexibank/iecor", "license": "CC-BY-4.0"},
    "wold": {"kind": "dataset", "title": "World Loanword Database (WOLD)", "editors": True,
             "authors": [P("Haspelmath", "Martin"), P("Tadmor", "Uri")],
             "year": 2009, "version": "v4.2", "publisher": MPI_EVA, "url": "https://wold.clld.org",
             "repository": "https://github.com/lexibank/wold", "license": "CC-BY-4.0"},
    "lexibank_analysed": {"kind": "dataset", "title": "Lexibank²: Precomputed Features for Large-Scale Lexical Data",
                          "authors": [P("Blum", "Frederic"), P("Barrientos", "Carlos"), P("Englisch", "Johannes"), P("Forkel", "Robert"),
                                      P("Gray", "Russell D."), P("Greenhill", "Simon J."), P("Rzymski", "Christoph"),
                                      P("List", "Johann-Mattis")],
                          "year": 2025, "version": "v2.2.6", "publisher": MPI_EVA, "url": "https://lexibank.clld.org",
                          "repository": "https://github.com/lexibank/lexibank-analysed", "license": "CC-BY-4.0"},
    "clics4": {"kind": "dataset", "title": "CLICS⁴: An Improved Database of Cross-Linguistic Colexifications",
               "authors": [P("Tjuka", "Annika"), P("Forkel", "Robert"), P("Rzymski", "Christoph"), P("List", "Johann-Mattis")],
               "year": 2026, "version": "v1.0", "publisher": ("MCL Chair at the University of Passau", "Passau"),
               "doi": "10.5281/zenodo.16900179", "repository": "https://github.com/clics/clics4", "license": "CC-BY-4.0"},
    "norare": {"kind": "dataset", "title": "NoRaRe: Database of Cross-Linguistic Norms, Ratings, and Relations for Words and Concepts",
               "authors": [P("Tjuka", "Annika"), P("Forkel", "Robert"), P("List", "Johann-Mattis")],
               "year": 2025, "version": "v1.1", "publisher": MPI_EVA, "url": "https://norare.clld.org",
               "repository": "https://github.com/concepticon/norare-data", "license": "CC-BY-4.0"},
    "phoible": {"kind": "dataset", "title": "PHOIBLE", "editors": True, "authors": [P("Moran", "Steven"), P("McCloy", "Daniel")],
                "year": 2019, "version": "v2.0.1", "publisher": ("Max Planck Institute for the Science of Human History", "Jena"),
                "url": "https://phoible.org", "repository": "https://github.com/cldf-datasets/phoible", "license": "CC-BY-4.0"},
    "wals": {"kind": "dataset", "title": "The World Atlas of Language Structures Online", "editors": True,
             "authors": [P("Dryer", "Matthew S."), P("Haspelmath", "Martin")],
             "year": 2013, "version": "v2020.5", "publisher": MPI_EVA, "url": "https://wals.info",
             "repository": "https://github.com/cldf-datasets/wals", "license": "CC-BY-4.0"},
    "grambank": {"kind": "dataset", "title": "Grambank", "et_al": True,
                 "authors": [P("Skirgård", "Hedvig"), P("Haynie", "Hannah J."), P("Blasi", "Damián E."), P("Hammarström", "Harald")],
                 "year": 2023, "version": "v1.0.3", "publisher": MPI_EVA, "url": "https://grambank.clld.org",
                 "repository": "https://github.com/grambank/grambank", "license": "CC-BY-4.0"},
    "dplace": {"kind": "article", "title": "D-PLACE: A Global Database of Cultural, Linguistic and Environmental Diversity",
               "authors": [P("Kirby", "Kathryn R."), P("Gray", "Russell D."), P("Greenhill", "Simon J."), P("Jordan", "Fiona M."),
                           P("Gomes-Ng", "Stephanie"), P("Bibiko", "Hans-Jörg"), P("Blasi", "Damián E."), P("Botero", "Carlos A."),
                           P("Bowern", "Claire"), P("Ember", "Carol R."), P("Leehr", "Dan"), P("Low", "Bobbi S."),
                           P("McCarter", "Joe"), P("Divale", "William"), P("Gavin", "Michael C.")],
               "year": 2016, "journal": "PLoS ONE", "volume": "11", "issue": "7", "pages": "e0158391",
               "doi": "10.1371/journal.pone.0158391", "url": "https://d-place.org", "version": "v3.2.0",
               "repository": "https://github.com/D-PLACE/dplace-cldf", "license": "CC-BY-NC-4.0"},
    "asjp": {"kind": "dataset", "title": "The ASJP Database", "editors": True,
             "authors": [P("Wichmann", "Søren"), P("Holman", "Eric W."), P("Brown", "Cecil H."), P("Dryer", "Matthew S."), P("Ran", "Qibin")],
             "year": 2025, "version": "v21.1", "url": "https://asjp.clld.org", "repository": "https://github.com/lexibank/asjp",
             "license": "CC-BY-4.0"},
    "datsemshift": {"kind": "dataset", "title": "Database of Semantic Shifts", "et_al": True, "authors": [P("Zalizniak", "Anna")],
                    "year": 2024, "version": "v1.1rc", "publisher": ("Institute of Linguistics, Russian Academy of Sciences", "Moscow"),
                    "url": "https://datsemshift.ru", "repository": "https://github.com/lexibank/datsemshift", "license": "CC-BY-4.0"},
    "lkezdb": {"kind": "dataset", "title": "Lietuvių kalbos etimologinio žodyno duomenų bazė (LKEŽDB)",
               "authors": [{"literal": "Lietuvių kalbos institutas"}], "publisher": ("Lietuvių kalbos institutas", "Vilnius"),
               "url": "https://etimologija.baltnexus.lt"},
}

# SODAS until the real CITATION.cff exists: everything here is made up (the DOI and the repository do not exist).
TRIAL_CFF: dict[str, Any] = {
    "cff-version": "1.2.0",
    "message": "Jei naudojate SODAS, cituokite jį taip.",
    "title": "SODAS: lingvistinių duomenų tyrimo aplinka",
    "type": "software",
    "authors": [{"family-names": "Račkaitis", "given-names": ""}],
    "version": "0.1.0",
    "doi": "10.5281/zenodo.0000000",
    "date-released": "2026-10-09",
    "repository-code": "https://github.com/pavyzdys/sodas",
    "url": "https://github.com/pavyzdys/sodas",
    "license": "CC-BY-4.0",
}
CFF_NAME = "CITATION.cff"
_cff_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}
_cff_lock = threading.Lock()


# ---------------------------------------------------------------- SODAS from CITATION.cff
def read_cff(paths: list[Path]) -> tuple[dict[str, Any], Path | None]:
    """The first readable CITATION.cff among ``paths`` (kept until it changes); else the trial one."""
    import yaml
    for path in paths:
        try:
            stamp = path.stat().st_mtime
        except OSError:
            continue
        with _cff_lock:
            hit = _cff_cache.get(str(path))
        if hit is None or hit[0] != stamp:
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
            except (OSError, yaml.YAMLError):
                data = None
            hit = (stamp, data if isinstance(data, dict) and data.get("title") else None)
            with _cff_lock:
                _cff_cache[str(path)] = hit
        if hit[1] is not None:
            return copy.deepcopy(hit[1]), path
    return copy.deepcopy(TRIAL_CFF), None


def _cff_people(people: Any) -> list[dict[str, str]]:
    out = []
    for p in people if isinstance(people, list) else []:
        if not isinstance(p, dict):
            continue
        if p.get("family-names"):
            family = " ".join(x for x in (p.get("name-particle"), p["family-names"]) if x)
            out.append({"family": str(family), "given": str(p.get("given-names") or "")})
        elif p.get("name"):
            out.append({"literal": str(p["name"])})
    return out


def _cff_doi(c: dict[str, Any]) -> str | None:
    if c.get("doi"):
        return str(c["doi"])
    for i in c.get("identifiers") or []:
        if isinstance(i, dict) and i.get("type") == "doi" and i.get("value"):
            return str(i["value"])
    return None


def _cff_entry(c: dict[str, Any], key: str) -> dict[str, Any]:
    released = str(c.get("date-released") or c.get("date-published") or "")[:10]
    year = int(released[:4]) if re.match(r"^\d{4}", released) else (int(c["year"]) if str(c.get("year", "")).isdigit() else None)
    kind = {"software": "software", "dataset": "dataset", "article": "article"}.get(str(c.get("type") or "software"), "software")
    pub = c.get("publisher") if isinstance(c.get("publisher"), dict) else {}
    lic = c.get("license")
    pages = f"{c['start']}–{c['end']}" if c.get("start") and c.get("end") else c.get("start")
    return {"key": key, "kind": kind, "title": str(c.get("title") or "SODAS"), "authors": _cff_people(c.get("authors")),
            "year": year, "date": released or None, "version": str(c["version"]) if c.get("version") else None,
            "doi": _cff_doi(c), "url": c.get("url") or c.get("repository-code"), "repository": c.get("repository-code"),
            "publisher": (pub.get("name"), pub.get("city")) if pub.get("name") else None,
            "license": ", ".join(lic) if isinstance(lic, list) else lic,
            "journal": c.get("journal") or None, "volume": c.get("volume"), "issue": c.get("issue"), "pages": pages}


def sodas_entries(paths: list[Path]) -> tuple[list[dict[str, Any]], bool]:
    """SODAS (and its preferred citation, when CITATION.cff names one): (entries, trial?)."""
    cff, found = read_cff(paths)
    main = _cff_entry(cff, "sodas")
    main["key"] = f"sodas{main['year'] or ''}"
    main["dataset"] = "sodas"
    out = [main]
    pref = cff.get("preferred-citation")
    if isinstance(pref, dict) and pref.get("title"):
        e = _cff_entry(pref, "")
        e["key"] = f"sodas{e['year'] or ''}_straipsnis"
        e["dataset"] = "sodas"
        out.append(e)
    trial = found is None
    for e in out:
        e["trial"] = trial
    return out, trial


# ---------------------------------------------------------------- datasets
def _from_folder(ds: str, folder: Path | None) -> dict[str, Any] | None:
    """A dataset outside the catalogue: from its folder's .zenodo.json / metadata.json."""
    if folder is None or not folder.is_dir():
        return None
    entry: dict[str, Any] = {"kind": "dataset", "title": ds, "authors": []}
    try:
        z = json.loads((folder / ".zenodo.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        z = {}
    try:
        m = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        m = {}
    for c in z.get("creators") or []:
        name = str(c.get("name") or "").strip()
        if "," in name:
            fam, giv = [x.strip() for x in name.split(",", 1)]
            entry["authors"].append(P(fam, giv))
        elif name:
            parts = name.rsplit(" ", 1)
            entry["authors"].append(P(parts[-1], parts[0] if len(parts) > 1 else ""))
    title = m.get("title") or m.get("dc:title") or z.get("title")
    if title:
        entry["title"] = str(title)
    if m.get("url") or m.get("dcat:accessURL"):
        entry["url"] = m.get("url") or m.get("dcat:accessURL")
    lic = m.get("license") or (z.get("license") or {}).get("id")
    if isinstance(lic, str):
        entry["license"] = lic
    if m.get("citation"):
        entry["note"] = re.sub(r"\s+", " ", html.unescape(str(m["citation"])))[:600]
    return entry


def dataset_entries(sources: dict[str, dict[str, Any]], versions: dict[str, dict[str, Any]],
                    folders: dict[str, Path] | None = None, titles: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """One entry per dataset and version used (the version found on this computer when the use was not dated)."""
    out = []
    for ds, used in sources.items():
        base = CATALOGUE.get(ds) or _from_folder(ds, (folders or {}).get(ds)) or \
            {"kind": "dataset", "title": (titles or {}).get(ds) or ds, "authors": []}
        live = versions.get(ds) or {}
        for v in used.get("versions") or [live.get("version") or base.get("version")]:
            e = copy.deepcopy(base)
            e.update(dataset=ds, version=v, first=used.get("first"), last=used.get("last"), trial=False)
            if v and v != base.get("version") and live.get("version") == v and live.get("date"):
                e["year"] = int(live["date"][:4])      # a newer release than the catalogue's: its own year
                e["date"] = live["date"]
            e["accessed"] = str(used.get("last") or "")[:10] or None
            e["key"] = re.sub(r"[^A-Za-z0-9_.-]", "", f"{ds}{e.get('year') or ''}" + (f"_{v}" if v else ""))
            out.append(e)
    out.sort(key=lambda e: (_first_name(e).lower(), e["title"].lower(), str(e.get("version") or "")))
    return out


def _first_name(e: dict[str, Any]) -> str:
    a = (e.get("authors") or [{}])[0]
    return a.get("family") or a.get("literal") or e.get("title") or ""


# ---------------------------------------------------------------- formats
FORMATS = {
    "bibtex": {"title": "BibTeX", "ext": "bib", "mime": "application/x-bibtex"},
    "biblatex": {"title": "BibLaTeX", "ext": "bib", "mime": "application/x-bibtex"},
    "ris": {"title": "RIS (EndNote, Zotero, Mendeley)", "ext": "ris", "mime": "application/x-research-info-systems"},
    "csl": {"title": "CSL-JSON (Zotero, Mendeley, Pandoc)", "ext": "json", "mime": "application/vnd.citationstyles.csl+json"},
    "tekstas": {"title": "Tekstas (APA)", "ext": "txt", "mime": "text/plain"},
}


def _tex(s: Any) -> str:
    return re.sub(r"([&%$#_])", r"\\\1", str(s))


def _names_tex(e: dict[str, Any]) -> str:
    names = [f"{{{_tex(a['literal'])}}}" if "literal" in a else _tex(f"{a['family']}, {a['given']}" if a.get("given") else a["family"])
             for a in e.get("authors") or []]
    if e.get("et_al"):
        names.append("others")
    return " and ".join(names)


def _publisher(e: dict[str, Any]) -> tuple[str | None, str | None]:
    p = e.get("publisher")
    return (p[0], p[1]) if isinstance(p, (list, tuple)) and p else (None, None)


def _fields_tex(fields: list[tuple[str, Any]]) -> str:
    rows = [f"  {k} = {{{v}}}" for k, v in fields if v not in (None, "")]
    return ",\n".join(rows)


def _note(e: dict[str, Any], with_version: bool) -> str:
    parts = []
    if with_version and e.get("version"):
        parts.append(f"Version {e['version']}")
    if e.get("editors"):
        parts.append("Eds.")
    if e.get("license"):
        parts.append(f"License: {e['license']}")
    if e.get("accessed"):
        parts.append(f"Accessed {e['accessed']}")
    if e.get("note"):
        parts.append(e["note"])
    if e.get("trial"):
        parts.append("RUOŠIAMA – DOI ir saugykla dar neskelbti")
    return ". ".join(_tex(p).rstrip(".") for p in parts)


def bibtex(entries: list[dict[str, Any]]) -> str:
    out = []
    for e in entries:
        pub, place = _publisher(e)
        if e["kind"] == "article":
            fields = [("author", _names_tex(e)), ("title", f"{{{_tex(e['title'])}}}"), ("journal", _tex(e.get("journal") or "")),
                      ("year", e.get("year")), ("volume", e.get("volume")), ("number", e.get("issue")), ("pages", e.get("pages")),
                      ("doi", e.get("doi")), ("url", e.get("url")), ("note", _note(e, True))]
            out.append(f"@article{{{e['key']},\n{_fields_tex(fields)}\n}}")
            continue
        fields = [("author", _names_tex(e)), ("title", f"{{{_tex(e['title'])}}}"), ("year", e.get("year")),
                  ("publisher", _tex(pub) if pub else None), ("address", _tex(place) if place else None),
                  ("howpublished", f"\\url{{{e['url']}}}" if e.get("url") else None), ("version", _tex(e.get("version") or "")),
                  ("doi", e.get("doi")), ("url", e.get("url")), ("urldate", e.get("accessed")), ("note", _note(e, True))]
        out.append(f"@misc{{{e['key']},\n{_fields_tex(fields)}\n}}")
    return "\n\n".join(out) + "\n"


def biblatex(entries: list[dict[str, Any]]) -> str:
    out = []
    for e in entries:
        pub, place = _publisher(e)
        who = "editor" if e.get("editors") else "author"
        note = ". ".join(x for x in (f"License: {_tex(e['license'])}" if e.get("license") else "", _tex(e.get("note") or ""),
                                     "RUOŠIAMA – DOI ir saugykla dar neskelbti" if e.get("trial") else "") if x)
        if e["kind"] == "article":
            fields = [("author", _names_tex(e)), ("title", f"{{{_tex(e['title'])}}}"), ("journaltitle", _tex(e.get("journal") or "")),
                      ("date", e.get("year")), ("volume", e.get("volume")), ("number", e.get("issue")), ("pages", e.get("pages")),
                      ("doi", e.get("doi")), ("url", e.get("url")), ("urldate", e.get("accessed")), ("note", note)]
            out.append(f"@article{{{e['key']},\n{_fields_tex(fields)}\n}}")
            continue
        fields = [(who, _names_tex(e)), ("title", f"{{{_tex(e['title'])}}}"), ("date", e.get("date") or e.get("year")),
                  ("version", _tex(e.get("version") or "")), ("publisher", _tex(pub) if pub else None),
                  ("location", _tex(place) if place else None), ("doi", e.get("doi")), ("url", e.get("url")),
                  ("eprinttype", "github" if str(e.get("repository") or "").startswith("https://github.com/") and e.get("repository") != e.get("url") else None),
                  ("eprint", str(e["repository"]).removeprefix("https://github.com/")
                   if str(e.get("repository") or "").startswith("https://github.com/") and e.get("repository") != e.get("url") else None),
                  ("urldate", e.get("accessed")), ("note", note)]
        out.append(f"@{'software' if e['kind'] == 'software' else 'dataset'}{{{e['key']},\n{_fields_tex(fields)}\n}}")
    return "\n\n".join(out) + "\n"


def ris(entries: list[dict[str, Any]]) -> str:
    out = []
    for e in entries:
        pub, place = _publisher(e)
        ty = {"article": "JOUR", "software": "COMP"}.get(e["kind"], "DATA")
        rows = [("TY", ty)]
        tag = "ED" if e.get("editors") else "AU"
        rows += [(tag, a.get("literal") or (f"{a['family']}, {a['given']}" if a.get("given") else a["family"])) for a in e.get("authors") or []]
        if e.get("et_al"):
            rows.append((tag, "et al."))
        rows += [("TI", e["title"]), ("PY", e.get("year")), ("DA", (e.get("date") or "").replace("-", "/") or None)]
        if e["kind"] == "article":
            rows += [("JO", e.get("journal")), ("VL", e.get("volume")), ("IS", e.get("issue")), ("SP", e.get("pages"))]
        else:
            rows += [("ET", e.get("version")), ("PB", pub), ("CY", place)]
        rows += [("DO", e.get("doi")), ("UR", e.get("url")), ("Y2", (e.get("accessed") or "").replace("-", "/") or None)]
        notes = [f"Version {e['version']}" if e["kind"] == "article" and e.get("version") else "",
                 f"License: {e['license']}" if e.get("license") else "", e.get("note") or "",
                 f"Repository: {e['repository']}" if e.get("repository") and e.get("repository") != e.get("url") else "",
                 "RUOŠIAMA – DOI ir saugykla dar neskelbti" if e.get("trial") else ""]
        rows += [("N1", n) for n in notes if n]
        rows.append(("ER", ""))
        out.append("\n".join(f"{k}  - {v}".rstrip() for k, v in rows if v not in (None, "") or k == "ER"))
    return "\n\n".join(out) + "\n"


def csl(entries: list[dict[str, Any]]) -> str:
    items = []
    for e in entries:
        pub, place = _publisher(e)
        people = [{"literal": a["literal"]} if "literal" in a else {"family": a["family"], "given": a.get("given") or ""}
                  for a in e.get("authors") or []]
        it: dict[str, Any] = {"id": e["key"], "type": {"article": "article-journal", "software": "software"}.get(e["kind"], "dataset"),
                              "title": e["title"], ("editor" if e.get("editors") else "author"): people}
        if e.get("date"):
            it["issued"] = {"date-parts": [[int(x) for x in e["date"].split("-")]]}
        elif e.get("year"):
            it["issued"] = {"date-parts": [[int(e["year"])]]}
        for k, v in (("version", e.get("version")), ("publisher", pub), ("publisher-place", place), ("DOI", e.get("doi")),
                     ("URL", e.get("url")), ("container-title", e.get("journal")), ("volume", e.get("volume")),
                     ("issue", e.get("issue")), ("page", e.get("pages"))):
            if v:
                it[k] = v
        if e.get("accessed"):
            it["accessed"] = {"date-parts": [[int(x) for x in e["accessed"].split("-")]]}
        notes = [f"License: {e['license']}" if e.get("license") else "", e.get("note") or "",
                 "RUOŠIAMA – DOI ir saugykla dar neskelbti" if e.get("trial") else ""]
        if any(notes):
            it["note"] = ". ".join(n for n in notes if n)
        items.append(it)
    return json.dumps(items, ensure_ascii=False, indent=2) + "\n"


def _apa_names(e: dict[str, Any]) -> str:
    names = []
    for a in e.get("authors") or []:
        if "literal" in a:
            names.append(a["literal"])
            continue
        initials = " ".join(w if w.endswith(".") else "-".join(f"{x[0]}." for x in w.split("-") if x)
                            for w in (a.get("given") or "").split() if w)
        names.append(f"{a['family']}, {initials}".rstrip(", "))
    if e.get("et_al"):
        return (names[0] if names else "") + ", et al."
    if len(names) > 1:
        return ", ".join(names[:-1]) + ", & " + names[-1]
    return names[0] if names else ""


def text(entries: list[dict[str, Any]]) -> str:
    out = []
    for e in entries:
        who = _apa_names(e)
        if e.get("editors"):
            who += " (Eds.)" if len(e.get("authors") or []) > 1 else " (Ed.)"
        year = f"({e['year']})" if e.get("year") else "(n.d.)"
        link = f"https://doi.org/{e['doi']}" if e.get("doi") else e.get("url") or ""
        if e["kind"] == "article":
            body = f"{e['title']}. {e.get('journal') or ''}, {e.get('volume') or ''}({e.get('issue') or ''}), {e.get('pages') or ''}."
        else:
            label = "[Computer software]" if e["kind"] == "software" else "[Data set]"
            version = f" (Version {e['version']})" if e.get("version") else ""
            body = f"{e['title']}{version} {label}."
            pub, _ = _publisher(e)
            if pub:
                body += f" {pub}."
        line = " ".join(x for x in (f"{who}." if who and not who.endswith(".") else who, year + ".", body, link) if x)
        if e.get("trial"):
            line += "  [RUOŠIAMA – DOI ir saugykla dar neskelbti]"
        out.append(line)
    return "\n\n".join(out) + "\n"


RENDER = {"bibtex": bibtex, "biblatex": biblatex, "ris": ris, "csl": csl, "tekstas": text}


def render(fmt: str, entries: list[dict[str, Any]]) -> str:
    if fmt not in RENDER:
        raise ValueError(f"nežinomas formatas: {fmt} (galimi: {', '.join(RENDER)})")
    return RENDER[fmt](entries)


def summary(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What the page lists above the formats: what is cited and when it was used."""
    return [{"key": e["key"], "dataset": e.get("dataset"), "title": e["title"], "version": e.get("version"), "year": e.get("year"),
             "first": e.get("first"), "last": e.get("last"), "trial": bool(e.get("trial")), "license": e.get("license"),
             "doi": e.get("doi"), "url": e.get("url")} for e in entries]


def today() -> str:
    return date.today().isoformat()


__all__ = ["CATALOGUE", "FORMATS", "TRIAL_CFF", "dataset_entries", "read_cff", "render", "sodas_entries", "summary"]
