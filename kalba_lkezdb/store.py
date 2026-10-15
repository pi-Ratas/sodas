"""The LKEŽDB SQLite store (puslapiai.db): scraped words, pages, articles and sources, plus our explanations,
jobs and settings. The scraped tables are only read; explanations live in ``zodzio_aiskinimai`` (one per word)."""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .text import article_texts


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


EXTRA_COLUMNS = {
    "zodzio_aiskinimai": {"uzklausos_id": "TEXT", "modelis": "TEXT", "naudojimas": "TEXT", "ispejimai": "TEXT",
                          "itraukta_kada": "TEXT"},
}


class Store:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.RLock()
        if path.exists():
            with self.connect() as c:
                self._migrate(c)

    @property
    def available(self) -> bool:
        return self.path.exists()

    def connect(self) -> sqlite3.Connection:
        if not self.path.exists():
            raise LookupError(f"LKEŽDB duomenų talpykla nerasta: {self.path}")
        c = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON")
        return c

    def _migrate(self, c: sqlite3.Connection) -> None:
        for table, cols in EXTRA_COLUMNS.items():
            have = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
            for name, typ in cols.items():
                if name not in have:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")
        c.commit()

    # -- settings --------------------------------------------------------------------------------------------------
    def setting(self, key: str, default: str = "") -> str:
        with self.connect() as c:
            r = c.execute("SELECT reiksme FROM app_nustatymai WHERE raktas = ?", (key,)).fetchone()
        return r["reiksme"] if r and r["reiksme"] is not None else default

    def set_setting(self, key: str, value: str) -> None:
        with self.lock, self.connect() as c:
            c.execute("INSERT INTO app_nustatymai(raktas, reiksme) VALUES(?, ?) ON CONFLICT(raktas) DO UPDATE SET reiksme = excluded.reiksme",
                      (key, value))

    # -- prompts ---------------------------------------------------------------------------------------------------
    def prompts(self) -> list[dict[str, Any]]:
        with self.connect() as c:
            return [dict(r) for r in c.execute("SELECT GUID, pavadinimas, turinys, sukurta, atnaujinta FROM uzklausos ORDER BY atnaujinta DESC")]

    def save_prompt(self, guid: str, name: str, text: str) -> None:
        with self.lock, self.connect() as c:
            c.execute("INSERT INTO uzklausos(GUID, pavadinimas, turinys) VALUES(?, ?, ?) ON CONFLICT(GUID) DO UPDATE SET "
                      "pavadinimas = excluded.pavadinimas, turinys = excluded.turinys, atnaujinta = CURRENT_TIMESTAMP", (guid, name, text))

    # -- words -----------------------------------------------------------------------------------------------------
    def stats(self) -> dict[str, int]:
        with self.connect() as c:
            r = c.execute("SELECT count(*) AS zodziai, sum(nuskaityta) AS nuskaityta, sum(isaiskinta) AS isaiskinta, "
                          "sum(itraukta) AS itraukta FROM zodziai").fetchone()
            a = c.execute("SELECT count(*) AS n FROM straipsniai").fetchone()["n"]
            q = c.execute("SELECT count(*) AS n FROM analizes_darbai WHERE busena IN ('pending', 'running')").fetchone()["n"]
        return {**{k: int(r[k] or 0) for k in r.keys()}, "straipsniai": int(a), "eileje": int(q)}

    def words(self, q: str = "", status: str = "", offset: int = 0, limit: int = 50) -> dict[str, Any]:
        where, args = [], []
        if q:
            where.append("(z.zodis LIKE ? OR z.zodis = ?)")
            args += [q.strip() + "%", q.strip()]
        if status == "isaiskinta":
            where.append("z.isaiskinta = 1")
        elif status == "itraukta":
            where.append("z.itraukta = 1")
        elif status == "neisaiskinta":
            where.append("z.isaiskinta = 0")
        sql_where = ("WHERE " + " AND ".join(where)) if where else ""
        with self.connect() as c:
            total = c.execute(f"SELECT count(*) AS n FROM zodziai z {sql_where}", args).fetchone()["n"]
            rows = c.execute(
                f"SELECT z.GUID, z.zodis, z.url, z.isaiskinta, z.itraukta, "
                f"(SELECT count(*) FROM straipsniai s WHERE s.LKEZDB_Puslapis = z.puslapio_GUID) AS straipsniai, "
                f"(SELECT busena FROM analizes_darbai d WHERE d.zodzio_GUID = z.GUID ORDER BY d.sukurta DESC LIMIT 1) AS darbas "
                f"FROM zodziai z {sql_where} ORDER BY z.zodis COLLATE NOCASE LIMIT ? OFFSET ?", args + [limit, offset]).fetchall()
        return {"total": total, "words": [dict(r) for r in rows]}

    def word(self, word_guid: str) -> dict[str, Any]:
        """The word, its page and articles (text read again from the page HTML, with italics as ⟨…⟩)."""
        with self.connect() as c:
            w = c.execute("SELECT * FROM zodziai WHERE GUID = ?", (word_guid,)).fetchone()
            if not w:
                raise LookupError("žodis nerastas")
            page = c.execute("SELECT GUID, LKEZDB_atsakymas FROM puslapiai WHERE GUID = ? OR LKEZDB_Zodis = ?",
                             (w["puslapio_GUID"], word_guid)).fetchone()
            arts = []
            if page:
                arts = [dict(r) for r in c.execute(
                    "SELECT s.GUID, s.antraste, s.reiksme, s.istrauka, s.saltinis AS saltinis_pilnas, s.metai, s.vieta_saltinyje, "
                    "src.GUID AS saltinio_GUID, src.santrumpa AS saltinis "
                    "FROM straipsniai s LEFT JOIN saltiniai src ON src.saltinis = s.saltinis "
                    "WHERE s.LKEZDB_Puslapis = ? ORDER BY s.antraste COLLATE NOCASE, s.GUID", (page["GUID"],))]
                texts = article_texts(page["LKEZDB_atsakymas"], arts)
                for a in arts:
                    a["tekstas"] = texts.get(a["GUID"]) or a["istrauka"] or ""
            expl = c.execute("SELECT * FROM zodzio_aiskinimai WHERE zodzio_GUID = ?", (word_guid,)).fetchone()
        return {"word": dict(w), "page_guid": page["GUID"] if page else None, "articles": arts,
                "explanation": _explanation(expl) if expl else None}

    def find_word(self, text: str) -> dict[str, Any] | None:
        with self.connect() as c:
            r = c.execute("SELECT GUID, zodis, isaiskinta, itraukta FROM zodziai WHERE GUID = ? OR zodis = ? ORDER BY zodis LIMIT 1",
                          (text, text)).fetchone()
        return dict(r) if r else None

    def source(self, abbreviation: str | None = None, full: str | None = None) -> dict[str, Any] | None:
        with self.connect() as c:
            r = c.execute("SELECT GUID, santrumpa, saltinis FROM saltiniai WHERE saltinis = ? OR santrumpa = ? LIMIT 2",
                          (full or "", abbreviation or "")).fetchall()
        return dict(r[0]) if len(r) == 1 else None

    def resolve_citation(self, raw: str | None, author: str | None, year: str | None) -> dict[str, Any] | None:
        """A citation in the text („Stang 1966, 380–381“) → the source list entry, only when unambiguous."""
        with self.connect() as c:
            cands = []
            if raw:
                head = raw.split(",")[0].split(":")[0].strip()
                cands = c.execute("SELECT GUID, santrumpa, saltinis FROM saltiniai WHERE santrumpa = ? OR santrumpa = ?", (raw.strip(), head)).fetchall()
            if not cands and author and year:
                cands = c.execute("SELECT GUID, santrumpa, saltinis FROM saltiniai WHERE santrumpa LIKE ? AND santrumpa LIKE ?",
                                  (f"%{author}%", f"%{year}%")).fetchall()
        return dict(cands[0]) if len(cands) == 1 else None

    # -- explanations ----------------------------------------------------------------------------------------------
    def save_explanation(self, word_guid: str, page_guid: str, semantic: dict, plan: dict, raw_answer: str, prompt: str,
                         prompt_id: str, model: str, usage: dict | None, warnings: list[str]) -> None:
        with self.lock, self.connect() as c:
            c.execute(
                "INSERT INTO zodzio_aiskinimai(GUID, zodzio_GUID, puslapio_GUID, numeris, grafo_importo_planas, semantinis_json, "
                "llm_atsakymas, aiskinimo_uzklausa, itraukta, uzklausos_id, modelis, naudojimas, ispejimai, atnaujinta) "
                "VALUES(?, ?, ?, 1, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?) ON CONFLICT(zodzio_GUID) DO UPDATE SET "
                "grafo_importo_planas = excluded.grafo_importo_planas, semantinis_json = excluded.semantinis_json, "
                "llm_atsakymas = excluded.llm_atsakymas, aiskinimo_uzklausa = excluded.aiskinimo_uzklausa, "
                "uzklausos_id = excluded.uzklausos_id, modelis = excluded.modelis, naudojimas = excluded.naudojimas, "
                "ispejimai = excluded.ispejimai, atnaujinta = excluded.atnaujinta",
                (str(uuid.uuid4()), word_guid, page_guid, json.dumps(plan, ensure_ascii=False), json.dumps(semantic, ensure_ascii=False),
                 raw_answer, prompt, prompt_id, model, json.dumps(usage or {}), json.dumps(warnings, ensure_ascii=False), now()))
            c.execute("UPDATE zodziai SET isaiskinta = 1 WHERE GUID = ?", (word_guid,))

    def replace_plan(self, word_guid: str, plan: dict, warnings: list[str]) -> None:
        with self.lock, self.connect() as c:
            c.execute("UPDATE zodzio_aiskinimai SET grafo_importo_planas = ?, ispejimai = ? WHERE zodzio_GUID = ?",
                      (json.dumps(plan, ensure_ascii=False), json.dumps(warnings, ensure_ascii=False), word_guid))

    def set_included(self, word_guid: str, included: bool) -> None:
        with self.lock, self.connect() as c:
            c.execute("UPDATE zodziai SET itraukta = ? WHERE GUID = ?", (1 if included else 0, word_guid))
            c.execute("UPDATE zodzio_aiskinimai SET itraukta = ?, itraukta_kada = ? WHERE zodzio_GUID = ?",
                      (1 if included else 0, now() if included else None, word_guid))

    def clear_included(self) -> None:
        with self.lock, self.connect() as c:
            c.execute("UPDATE zodziai SET itraukta = 0")
            c.execute("UPDATE zodzio_aiskinimai SET itraukta = 0, itraukta_kada = NULL")

    def included_words(self) -> list[str]:
        with self.connect() as c:
            return [r["GUID"] for r in c.execute("SELECT GUID FROM zodziai WHERE itraukta = 1")]

    # -- jobs ------------------------------------------------------------------------------------------------------
    def enqueue(self, word_guid: str, include: bool) -> str:
        with self.lock, self.connect() as c:
            active = c.execute("SELECT GUID FROM analizes_darbai WHERE zodzio_GUID = ? AND busena IN ('pending', 'running')",
                               (word_guid,)).fetchone()
            if active:
                return active["GUID"]
            job = str(uuid.uuid4())
            c.execute("INSERT INTO analizes_darbai(GUID, zodzio_GUID, busena, auto_itraukti) VALUES(?, ?, 'pending', ?)",
                      (job, word_guid, 1 if include else 0))
            return job

    def claim_job(self) -> dict[str, Any] | None:
        with self.lock, self.connect() as c:
            r = c.execute("SELECT * FROM analizes_darbai WHERE busena = 'pending' ORDER BY sukurta LIMIT 1").fetchone()
            if not r:
                return None
            c.execute("UPDATE analizes_darbai SET busena = 'running', pradeta = ?, atnaujinta = ? WHERE GUID = ?", (now(), now(), r["GUID"]))
            return dict(r)

    def finish_job(self, job: str, status: str, result: str = "", error: str = "") -> None:
        with self.lock, self.connect() as c:
            c.execute("UPDATE analizes_darbai SET busena = ?, rezultatas = ?, klaida = ?, baigta = ?, atnaujinta = ? WHERE GUID = ?",
                      (status, result, error, now(), now(), job))

    def reset_running_jobs(self) -> None:
        """Jobs left 'running' by a stopped server go back to the queue."""
        with self.lock, self.connect() as c:
            c.execute("UPDATE analizes_darbai SET busena = 'pending' WHERE busena = 'running'")

    def jobs(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as c:
            return [dict(r) for r in c.execute(
                "SELECT d.GUID, d.zodzio_GUID, z.zodis, d.busena, d.auto_itraukti, d.klaida, d.rezultatas, d.sukurta, d.pradeta, d.baigta "
                "FROM analizes_darbai d LEFT JOIN zodziai z ON z.GUID = d.zodzio_GUID ORDER BY d.sukurta DESC LIMIT ?", (limit,))]

    def clear_jobs(self, statuses: tuple[str, ...] = ("done", "failed")) -> int:
        with self.lock, self.connect() as c:
            return c.execute(f"DELETE FROM analizes_darbai WHERE busena IN ({','.join('?' * len(statuses))})", statuses).rowcount


def _explanation(r: sqlite3.Row) -> dict[str, Any]:
    d = dict(r)
    for k in ("grafo_importo_planas", "semantinis_json", "naudojimas", "ispejimai"):
        try:
            d[k] = json.loads(d[k]) if d.get(k) else None
        except (TypeError, json.JSONDecodeError):
            pass
    return d
