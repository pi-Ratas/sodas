"""LKEŽDB → Neo4j: build the prompt, ask the model, check the answer, plan the graph, include or remove it."""
from __future__ import annotations

import json
import threading
import time
import traceback
from importlib import resources
from pathlib import Path
from typing import Any, Callable

from . import graph_io, llm, plan
from .store import Store
from .text import cross_reference, plain

SCHEMA_MARK = "<!-- kalba-lkezdb-schema: 1 -->"
BUILTIN = "lkezdb_grafas_1_0.md"


def builtin_prompts() -> dict[str, str]:
    root = resources.files("kalba_lkezdb").joinpath("uzklausos")
    return {p.name: p.read_text(encoding="utf-8") for p in root.iterdir() if p.name.endswith(".md")}


class Lkezdb:
    def __init__(self, db_path: Path, neo4j_settings: Callable[[], dict[str, str]], log=lambda *a: None):
        self.store = Store(db_path)
        self.graph = graph_io.Graph(neo4j_settings)
        self.log = log
        self.worker: threading.Thread | None = None
        self.stop = threading.Event()
        if self.store.available:
            self._install_prompts()
            self.store.reset_running_jobs()

    # -- prompts: only those written for this program (schema mark) can be chosen ---------------------------------------
    def _install_prompts(self) -> None:
        for name, text in builtin_prompts().items():
            self.store.save_prompt(f"builtin:{name}", name, text)
        active = self.store.setting("lkezdb_uzklausa")
        if not active or not any(p["GUID"] == active for p in self.prompts()):
            self.store.set_setting("lkezdb_uzklausa", f"builtin:{BUILTIN}")

    def prompts(self) -> list[dict[str, Any]]:
        return [{**p, "active": False} for p in self.store.prompts() if SCHEMA_MARK in (p["turinys"] or "")]

    def prompt_list(self) -> dict[str, Any]:
        active = self.store.setting("lkezdb_uzklausa")
        return {"active": active, "prompts": [{"GUID": p["GUID"], "name": p["pavadinimas"], "updated": p["atnaujinta"],
                                               "builtin": p["GUID"].startswith("builtin:"), "length": len(p["turinys"])} for p in self.prompts()]}

    def prompt_text(self, guid: str | None = None) -> tuple[str, str]:
        guid = guid or self.store.setting("lkezdb_uzklausa")
        for p in self.prompts():
            if p["GUID"] == guid:
                return guid, p["turinys"]
        raise LookupError("užklausa nerasta")

    def save_prompt(self, name: str, text: str, activate: bool = True) -> str:
        if SCHEMA_MARK not in text:
            raise ValueError(f"Užklausos pradžioje turi būti žymė {SCHEMA_MARK}: ji rodo, kad užklausa tinka šios programos atsakymo schemai.")
        import uuid
        guid = str(uuid.uuid4())
        self.store.save_prompt(guid, name, text)
        if activate:
            self.store.set_setting("lkezdb_uzklausa", guid)
        return guid

    def select_prompt(self, guid: str) -> None:
        self.prompt_text(guid)
        self.store.set_setting("lkezdb_uzklausa", guid)

    # -- one word ------------------------------------------------------------------------------------------------
    def payload(self, word_guid: str) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
        """(word data, what the model gets, articles the model must analyse)."""
        w = self.store.word(word_guid)
        for_llm = [a for a in w["articles"] if plain(a["tekstas"]).strip() and not cross_reference(a["tekstas"])]
        payload = {"zodis": {"GUID": w["word"]["GUID"], "zodis": w["word"]["zodis"]},
                   "straipsniai": [{"GUID": a["GUID"], "antraste": a["antraste"], "reiksme": a["reiksme"] or None,
                                    "tekstas": a["tekstas"], "saltinis": a["saltinis"] or a["saltinis_pilnas"], "metai": a["metai"],
                                    "vieta_saltinyje": a["vieta_saltinyje"]} for a in for_llm]}
        return w, payload, for_llm

    def prompt(self, word_guid: str) -> dict[str, Any]:
        guid, template = self.prompt_text()
        w, payload, for_llm = self.payload(word_guid)
        text = f"{template.strip()}\n\n## Analizuojamas žodis\n\n```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```\n"
        return {"prompt_id": guid, "prompt": text, "articles": len(w["articles"]), "for_model": len(for_llm)}

    def explain(self, word_guid: str) -> dict[str, Any]:
        w, payload, for_llm = self.payload(word_guid)
        p = self.prompt(word_guid)
        if for_llm:
            answer, model, usage = llm.complete(self.store, p["prompt"])
            parsed = llm.parse_answer(answer)
        else:
            answer, model, usage, parsed = "", "", {}, {"articles": []}
        analysis, warnings = plan.check(parsed, [a["GUID"] for a in for_llm])
        graph = plan.build(w["word"], w["articles"], analysis, self.store, self.graph.run, warnings)
        self.store.save_explanation(word_guid, w["page_guid"], analysis, graph, answer, p["prompt"], p["prompt_id"], model, usage, warnings)
        return {"word": w["word"]["zodis"], "nodes": len(graph["nodes"]), "relationships": len(graph["relationships"]),
                "warnings": warnings, "usage": usage, "model": model}

    def replan(self, word_guid: str) -> dict[str, Any]:
        """The saved analysis planned again (after program changes), without asking the model."""
        w = self.store.word(word_guid)
        ex = w["explanation"]
        if not ex or not ex.get("semantinis_json"):
            raise LookupError("žodis dar neišaiškintas")
        expected = [a["GUID"] for a in w["articles"] if plain(a["tekstas"]).strip() and not cross_reference(a["tekstas"])]
        analysis, warnings = plan.check(ex["semantinis_json"], expected)
        graph = plan.build(w["word"], w["articles"], analysis, self.store, self.graph.run, warnings)
        self.store.replace_plan(word_guid, graph, warnings)
        return {"nodes": len(graph["nodes"]), "relationships": len(graph["relationships"]), "warnings": warnings}

    def include(self, word_guid: str) -> dict[str, Any]:
        w = self.store.word(word_guid)
        ex = w["explanation"]
        if not ex or not ex.get("grafo_importo_planas"):
            raise LookupError("žodis dar neišaiškintas")
        graph = ex["grafo_importo_planas"]
        if graph.get("version") != plan.PLAN_VERSION:
            self.replan(word_guid)
            graph = self.store.word(word_guid)["explanation"]["grafo_importo_planas"]
        result = graph_io.write_plan(self.graph, graph)
        self.store.set_included(word_guid, True)
        return result

    def remove(self, word_guid: str) -> dict[str, Any]:
        w = self.store.word(word_guid)
        records = [plan.record_key(a["GUID"]) for a in w["articles"]]
        result = graph_io.remove_records(self.graph, records)
        self.store.set_included(word_guid, False)
        return result

    def delete_all(self) -> dict[str, Any]:
        result = graph_io.delete_all(self.graph)
        self.store.clear_included()
        return result

    def counts(self) -> dict[str, Any]:
        return graph_io.counts(self.graph)

    # -- queue -----------------------------------------------------------------------------------------------------
    def enqueue(self, word_guids: list[str], include: bool = True) -> list[str]:
        jobs = [self.store.enqueue(g, include) for g in word_guids]
        self.start_worker()
        return jobs

    def start_worker(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        self.worker = threading.Thread(target=self._work, daemon=True, name="lkezdb-darbai")
        self.worker.start()

    def _work(self) -> None:
        while not self.stop.is_set():
            job = self.store.claim_job()
            if not job:
                return
            try:
                result = self.explain(job["zodzio_GUID"])
                if job["auto_itraukti"]:
                    result["included"] = self.include(job["zodzio_GUID"])
                self.store.finish_job(job["GUID"], "done", json.dumps(result, ensure_ascii=False))
            except Exception as exc:  # noqa: BLE001 – kept in the job and the log
                self.store.finish_job(job["GUID"], "failed", error=str(exc))
                self.log("error", "lkezdb", f"žodžio aiškinimas nepavyko: {exc}", traceback.format_exc(limit=5))
                time.sleep(1)
