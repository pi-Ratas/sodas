"""Flags for languages: a language with a clear national (or regional) flag gets it as a picture of its Languoid.

The pictures are the SVG flags of the flag-icons package (MIT licence, https://github.com/lipis/flag-icons), saved
among the garden's own pictures. A rule "Languoid · display_name · <name> → flag" is added for every name the
language has in Neo4j (Glottolog, IE-CoR, DatSemShift, LKEŽDB name it differently), so forms and lexemes show the
flag of their language. Historical stages ("Old Czech", "Classical Arabic") get none. Existing rules are kept.
Every rule gets a ``title`` – the country or region of the flag (shown when the pointer rests on it); flag rules made
before titles existed get theirs the next time flags are assigned."""
from __future__ import annotations

import re
import urllib.request
from typing import Any, Callable

FLAG_URL = "https://cdn.jsdelivr.net/npm/flag-icons@7.5.0/flags/4x3/{code}.svg"

# Glottolog code → flag-icons code (ISO 3166-1, or a region such as gb-wls)
FLAGS = {
    # Baltic, Finnic
    "lith1251": "lt", "samo1265": "lt", "latv1249": "lv", "esto1258": "ee", "finn1318": "fi",
    # Slavic
    "russ1263": "ru", "bela1254": "by", "ukra1253": "ua", "poli1260": "pl", "czec1258": "cz", "slov1269": "sk",
    "slov1268": "si", "croa1245": "hr", "serb1264": "rs", "bosn1245": "ba", "mont1282": "me", "bulg1262": "bg", "mace1250": "mk",
    # Germanic
    "stan1295": "de", "stan1293": "gb", "dutc1256": "nl", "afri1274": "za", "luxe1241": "lu", "dani1285": "dk",
    "swed1254": "se", "norw1258": "no", "icel1247": "is", "faro1244": "fo", "west2354": "nl",
    # Romance
    "stan1290": "fr", "ital1282": "it", "stan1288": "es", "port1283": "pt", "roma1327": "ro", "stan1289": "es-ct",
    "gali1258": "es-ga", "roma1326": "ch",
    # Celtic
    "iris1253": "ie", "wels1247": "gb-wls", "scot1245": "gb-sct", "manx1243": "im",
    # other Indo-European
    "mode1248": "gr", "gheg1238": "al", "tosk1239": "al", "nucl1235": "am", "west2369": "ir", "dari1249": "af",
    "taji1245": "tj", "hind1269": "in", "urdu1245": "pk", "beng1280": "bd", "nepa1254": "np", "sinh1246": "lk",
    # other languages of Europe and nearby
    "basq1248": "es-pv", "hung1274": "hu", "malt1254": "mt", "nucl1302": "ge", "nucl1301": "tr", "nort2697": "az",
    "kaza1248": "kz", "nort2690": "uz", "turk1304": "tm", "kirg1245": "kg", "halh1238": "mn", "hebr1245": "il",
    "stan1318": "sa", "amha1245": "et", "soma1255": "so", "swah1253": "tz", "kala1399": "gl",
    # Asia and the Pacific
    "mand1415": "cn", "nucl1643": "jp", "kore1280": "kr", "viet1252": "vn", "thai1261": "th", "laoo1244": "la",
    "nucl1310": "mm", "indo1316": "id", "stan1306": "my", "taga1270": "ph", "dzon1239": "bt", "maor1246": "nz",
    "samo1305": "ws", "fiji1243": "fj", "hawa1245": "us",
}
# flag-icons code → the country or region in Lithuanian (the hint over the flag)
PLACES = {
    "lt": "Lietuva", "lv": "Latvija", "ee": "Estija", "fi": "Suomija", "ru": "Rusija", "by": "Baltarusija", "ua": "Ukraina",
    "pl": "Lenkija", "cz": "Čekija", "sk": "Slovakija", "si": "Slovėnija", "hr": "Kroatija", "rs": "Serbija",
    "ba": "Bosnija ir Hercegovina", "me": "Juodkalnija", "bg": "Bulgarija", "mk": "Šiaurės Makedonija", "de": "Vokietija",
    "gb": "Jungtinė Karalystė", "nl": "Nyderlandai", "za": "Pietų Afrika", "lu": "Liuksemburgas", "dk": "Danija",
    "se": "Švedija", "no": "Norvegija", "is": "Islandija", "fo": "Farerų salos", "fr": "Prancūzija", "it": "Italija",
    "es": "Ispanija", "pt": "Portugalija", "ro": "Rumunija", "es-ct": "Katalonija (Ispanija)", "es-ga": "Galisija (Ispanija)",
    "ch": "Šveicarija", "ie": "Airija", "gb-wls": "Velsas (Jungtinė Karalystė)", "gb-sct": "Škotija (Jungtinė Karalystė)",
    "im": "Meno sala", "gr": "Graikija", "al": "Albanija", "am": "Armėnija", "ir": "Iranas", "af": "Afganistanas",
    "tj": "Tadžikija", "in": "Indija", "pk": "Pakistanas", "bd": "Bangladešas", "np": "Nepalas", "lk": "Šri Lanka",
    "es-pv": "Baskija (Ispanija)", "hu": "Vengrija", "mt": "Malta", "ge": "Sakartvelas", "tr": "Turkija", "az": "Azerbaidžanas",
    "kz": "Kazachstanas", "uz": "Uzbekistanas", "tm": "Turkmėnistanas", "kg": "Kirgizija", "mn": "Mongolija", "il": "Izraelis",
    "sa": "Saudo Arabija", "et": "Etiopija", "so": "Somalis", "tz": "Tanzanija", "gl": "Grenlandija", "cn": "Kinija",
    "jp": "Japonija", "kr": "Pietų Korėja", "vn": "Vietnamas", "th": "Tailandas", "la": "Laosas", "mm": "Mianmaras",
    "id": "Indonezija", "my": "Malaizija", "ph": "Filipinai", "bt": "Butanas", "nz": "Naujoji Zelandija", "ws": "Samoa",
    "fj": "Fidžis", "us": "Jungtinės Amerikos Valstijos",
}
# a language whose flag stands for a smaller place than the whole country
PLACE_OF_LANGUAGE = {"samo1265": "Žemaitija (Lietuva)", "west2354": "Fryzija (Nyderlandai)", "hawa1245": "Havajai (JAV)",
                     "roma1326": "Graubiundenas (Šveicarija)"}


def flag_title(code: str, glottocode: str | None = None) -> str:
    return PLACE_OF_LANGUAGE.get(glottocode or "") or PLACES.get(code, code.upper())


HISTORICAL = re.compile(r"^(old|middle|classical|ancient|proto|early|archaic|medieval|new|modern written)\b", re.I)


def fetch_flag(code: str) -> bytes:
    with urllib.request.urlopen(FLAG_URL.format(code=code), timeout=20) as r:  # noqa: S310 – a fixed https address
        return r.read()


def language_names(read: Callable[..., list[Any]]) -> dict[str, set[str]]:
    """Flag code → the display names of every Languoid (any dataset) of a language with that flag."""
    return {flag: set(names) for flag, names in _names_with_titles(read).items()}


def _names_with_titles(read: Callable[..., list[Any]]) -> dict[str, dict[str, str]]:
    """Flag code → {display name → the place shown over the flag}."""
    rows = read("MATCH (l:Languoid) WHERE l.glottocode IN $codes AND l.display_name IS NOT NULL "
                "RETURN l.glottocode AS code, l.display_name AS name", codes=sorted(FLAGS))
    out: dict[str, dict[str, str]] = {}
    for r in rows:
        name = str(r["name"]).strip()
        if name and not HISTORICAL.match(name):
            flag = FLAGS[r["code"]]
            out.setdefault(flag, {})[name] = flag_title(flag, r["code"])
    return out


def assign_flags(store, read: Callable[..., list[Any]], fetch: Callable[[str], bytes] = fetch_flag) -> dict[str, Any]:
    """Add the missing flag rules to the settings and give the flag rules without a title their place; returns what was
    added and the new settings."""
    names = _names_with_titles(read)
    settings = store.settings()
    rules = settings["valueImages"]
    taken = {(r.get("label"), r.get("property"), str(r.get("value"))) for r in rules}
    titled = 0
    title_of = {n: t for langs in names.values() for n, t in langs.items()}
    for r in rules:
        if not r.get("title") and r.get("label") == "Languoid" and r.get("property") == "display_name" and str(r.get("value")) in title_of:
            r["title"] = title_of[str(r["value"])]
            titled += 1
    added, failed = [], []
    for flag, langs in sorted(names.items()):
        wanted = sorted(n for n in langs if ("Languoid", "display_name", n) not in taken)
        if not wanted:
            continue
        try:
            url = store.save_image(f"{flag}.svg", fetch(flag))
        except Exception as exc:  # noqa: BLE001 – no network, unknown flag: the others still get theirs
            failed.append(f"{flag}: {exc}")
            continue
        for n in wanted:
            rules.append({"label": "Languoid", "property": "display_name", "value": n, "image": url, "title": langs[n]})
            added.append(n)
    if added or titled:
        settings = store.save_settings(settings)
    return {"added": added, "titled": titled, "failed": failed, "settings": settings}
