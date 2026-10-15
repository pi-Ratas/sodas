"""OpenAI-compatible chat/completions engine (ChatGPT, LM Studio, other compatible servers).

Settings stay where the former program kept them (``app_nustatymai``: ``engine_<provider>_api_url`` …). The key is
taken from ``OPENAI_API_KEY`` first, then from the settings (the older shared ``engine_api_key`` too)."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .schema import response_schema

PROVIDERS = {
    "chatgpt": {"label": "ChatGPT (OpenAI)", "url": "https://api.openai.com/v1/chat/completions", "model": "gpt-4.1"},
    "lmstudio": {"label": "LM Studio", "url": "http://localhost:1234/v1/chat/completions", "model": ""},
    "openai_compatible": {"label": "OpenAI suderinamas", "url": "http://localhost:1234/v1/chat/completions", "model": ""},
}
SYSTEM = ("Atlik LKEŽDB straipsnių semantinę-etimologinę analizę pagal nurodymus. Negeneruok Cypher, UUID ar duomenų "
          "bazės objektų. Atsakyk tik vienu validžiu JSON objektu.")


KEY_FILE = ".raktas"


class EngineError(RuntimeError):
    pass


def key_file(store) -> Path:
    """The key file: $KALBA_RAKTAS, else ``.raktas`` in the project folder (above ``duomenynai/lkezdb/``), else in the working folder."""
    if os.environ.get("KALBA_RAKTAS"):
        return Path(os.environ["KALBA_RAKTAS"]).expanduser()
    project = Path(store.path).resolve().parents[2] / KEY_FILE
    return project if project.exists() else Path.cwd() / KEY_FILE


def read_key_file(path: Path) -> str:
    """The key from the file, read every time (a new key needs no restart). Accepts a bare key or ``OPENAI_API_KEY=…``;
    empty lines and ``#`` comments are skipped."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            line = line.split("=", 1)[1]
        return line.strip().strip('"').strip("'")
    return ""


def engine(store) -> dict[str, Any]:
    provider = store.setting("engine_active_provider", "chatgpt")
    if provider not in PROVIDERS:
        provider = "chatgpt"
    get = lambda name, default="": store.setting(f"engine_{provider}_{name}", default)
    kf = key_file(store)
    sources = [("aplinkos kintamasis OPENAI_API_KEY", os.environ.get("OPENAI_API_KEY", "")),
               (f"byla {kf}", read_key_file(kf) if provider == "chatgpt" else ""), ("šio tiekėjo nustatymas", get("api_key")),
               ("senas bendras nustatymas (iš ankstesnės programos)", store.setting("engine_api_key") if provider == "chatgpt" else "")]
    key_from, key = next(((name, k) for name, k in sources if k), ("", ""))
    return {"provider": provider, "url": get("api_url") or PROVIDERS[provider]["url"], "model": get("model") or PROVIDERS[provider]["model"],
            "json_schema": get("use_json_schema", "1") != "0", "key": key, "key_from": key_from}


def public_engine(store) -> dict[str, Any]:
    e = engine(store)
    hint = f"{e['key'][:12]}…{e['key'][-4:]}" if len(e["key"]) > 20 else ("nustatytas" if e["key"] else "")
    return {**{k: v for k, v in e.items() if k != "key"}, "has_key": bool(e["key"]), "key_hint": hint,
            "providers": [{"id": k, "label": v["label"]} for k, v in PROVIDERS.items()]}


def save_engine(store, values: dict[str, Any]) -> dict[str, Any]:
    provider = values.get("provider") or store.setting("engine_active_provider", "chatgpt")
    if provider not in PROVIDERS:
        raise ValueError("nežinomas tiekėjas")
    store.set_setting("engine_active_provider", provider)
    for name, key in (("url", "api_url"), ("model", "model")):
        if values.get(name) is not None:
            store.set_setting(f"engine_{provider}_{key}", str(values[name]).strip())
    if values.get("json_schema") is not None:
        store.set_setting(f"engine_{provider}_use_json_schema", "1" if values["json_schema"] else "0")
    if values.get("key"):
        key = str(values["key"]).strip()
        if provider == "chatgpt":
            # one place for the key: the same file as when it is changed by hand
            path = key_file(store)
            path.write_text(key + "\n", encoding="utf-8")
            path.chmod(0o600)
        else:
            store.set_setting(f"engine_{provider}_api_key", key)
    return public_engine(store)


def models(store) -> list[str]:
    e = engine(store)
    url = e["url"].rsplit("/chat/completions", 1)[0] + "/models"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {e['key']}"} if e["key"] else {})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
        raise EngineError(f"Modelių sąrašo gauti nepavyko: {exc}")
    return sorted(m.get("id") for m in data.get("data", []) if m.get("id"))


def complete(store, prompt: str, timeout: int = 900) -> tuple[str, str, dict[str, Any]]:
    """(answer text, model, usage). Falls back to plain JSON mode if the server rejects a JSON schema."""
    e = engine(store)
    if e["provider"] == "chatgpt" and not e["key"]:
        raise EngineError("Nerastas API raktas: įrašykite jį nustatymuose arba OPENAI_API_KEY.")
    if not e["model"]:
        raise EngineError("Nepasirinktas modelis.")
    body: dict[str, Any] = {"model": e["model"], "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]}
    if e["json_schema"]:
        body["response_format"] = {"type": "json_schema", "json_schema": {"name": "lkezdb_analize", "strict": True, "schema": response_schema()}}
    headers = {"Content-Type": "application/json"}
    if e["key"]:
        headers["Authorization"] = f"Bearer {e['key']}"
    req = urllib.request.Request(e["url"], data=json.dumps(body, ensure_ascii=False).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        if e["json_schema"] and ("response_format" in detail or "json_schema" in detail):
            store.set_setting(f"engine_{e['provider']}_use_json_schema", "0")
            return complete(store, prompt, timeout)
        raise EngineError(f"Variklio klaida {exc.code}: {detail[:800]}")
    except (urllib.error.URLError, TimeoutError) as exc:
        raise EngineError(f"Variklio API nepasiekiamas: {exc}")
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise EngineError(f"Netikėtas variklio atsakymas: {exc}")
    return content, data.get("model") or e["model"], data.get("usage") or {}


def parse_answer(text: str) -> dict[str, Any]:
    """The JSON object in the answer (also when a model wraps it in ```json fences or adds words around it)."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        start, end = t.find("{"), t.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(t[start:end + 1])
            except json.JSONDecodeError:
                pass
    raise EngineError("Atsakymas nėra JSON objektas.")


def check_key(store, test: bool = False) -> dict[str, Any]:
    """Which key the program uses and where from; with ``test`` also one tiny request (a fraction of a cent)."""
    e = public_engine(store)
    out = {"tiekėjas": e["provider"], "raktas": e["key_hint"] or "nėra", "iš kur": e["key_from"] or "–", "byla": str(key_file(store)),
           "modelis": e["model"]}
    if test:
        key = engine(store)["key"]
        body = {"model": "gpt-4.1-nano", "messages": [{"role": "user", "content": "Atsakyk vienu žodžiu: labas"}], "max_completion_tokens": 5}
        req = urllib.request.Request(e["url"], data=json.dumps(body).encode("utf-8"), method="POST",
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                json.loads(r.read().decode("utf-8"))
            out["patikra"] = "raktas veikia, kreditų yra"
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            try:
                err = json.loads(detail)["error"]
                out["patikra"] = f"klaida {exc.code}: {err.get('code') or err.get('type')} – {err.get('message')}"
            except (ValueError, KeyError, TypeError):
                out["patikra"] = f"klaida {exc.code}: {detail[:300]}"
        except (urllib.error.URLError, TimeoutError) as exc:
            out["patikra"] = f"API nepasiekiamas: {exc}"
    return out
