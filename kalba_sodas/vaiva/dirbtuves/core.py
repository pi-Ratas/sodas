"""Vaivos dirbtuvės: the parts (detalės), the data that flows between them and the runner of a setup.

A setup (sąranka) is a small graph drawn in the browser::

    {"blocks": [{"id": "b1", "type": "formos", "params": {...}, "x": 40, "y": 60}, ...],
     "links":  [{"from": ["b1", "formos"], "to": ["b2", "formos"]}, ...]}

Every block is a part registered with ``@part``. A part declares its input and output ports with their data types
(TYPES), its parameters, and a function ``fn(ctx, inputs, params) -> {output port: value}``. A view part (``view=True``)
has no outputs: it returns a fruit (vaisius) – ``{"kind": ..., "data": ..., "tiles": [...], "notes": [...]}`` – which
the page draws with the view registered for that kind (``VIEWS`` in static/dirbtuves.js).

To add a part: write such a function in any module of this package (it is imported by ``__init__``) – nothing else
has to change; a new kind of fruit also needs its drawing function in static/dirbtuves.js. Parts must not change their
inputs (results are kept in a cache and shared between runs).
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
import traceback
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from typing import Any, Callable

import numpy as np

# data type id → (name shown, what it is)
TYPES: dict[str, tuple[str, str]] = {
    "basket": ("Krepšys", "šios kortelės sodo krepšio mazgai"),
    "items": ("Vienetai", "tiriami vienetai (formos, kalbos, sąvokos) su savo požymiais"),
    "dist": ("Atstumai", "kiekvienos vienetų poros atstumas: 0 – tas pats, daugiau – toliau"),
    "sim": ("Panašumai", "kiekvienos vienetų poros panašumas: daugiau – panašiau"),
    "graph": ("Grafas", "svertinis grafas: vienetai – viršūnės, svoris – ryšio stiprumas"),
    "spectrum": ("Spektras", "grafo normalizuotos Laplaso matricos savosios reikšmės ir vektoriai"),
    "partition": ("Skaidinys", "vienetų suskirstymas į grupes"),
    "layout": ("Išdėstymas", "vienetų vietos plokštumoje"),
    "tree": ("Medis", "hierarchinis vienetų medis (dendrograma)"),
    "scores": ("Rodikliai", "skaitiniai kiekvieno vieneto rodikliai"),
}
ANY = "*"          # an input that takes any type that has vienetai
SAME = "="         # an output of the same type as an input: "=port"

GROUPS = ["Šaltiniai", "Matai", "Grafai", "Sietai", "Spektrinė analizė", "Rodikliai", "Vaisiai"]


# ---------------------------------------------------------------- the data
@dataclass
class Items:
    """What is studied: one row per unit – ``key``, ``name`` and attributes; ``_``-prefixed ones are for parts only
    (``_label`` the Neo4j label of the node, ``_path`` / ``_path_names`` the Glottolog lineage …). ``data``: bulk
    data of the source shared by all subsets."""
    kind: str
    rows: list[dict[str, Any]]
    data: dict[str, Any] = field(default_factory=dict)
    type = "items"

    @property
    def items(self) -> "Items":
        return self

    def __len__(self) -> int:
        return len(self.rows)

    def keys(self) -> list[str]:
        return [r["key"] for r in self.rows]

    def take(self, idx) -> "Items":
        return Items(self.kind, [self.rows[int(i)] for i in idx], self.data)

    def describe(self) -> str:
        return f"{len(self)} {KIND_PLURAL.get(self.kind, self.kind)}"


KIND_PLURAL = {"forma": "formos(-ų)", "kalba": "kalbos(-ų)", "sąvoka": "sąvokos(-ų)"}


@dataclass
class Matrix:
    """A square matrix over the items (NaN – unknown)."""
    items: Items
    m: np.ndarray
    label: str = ""
    extra: dict[str, np.ndarray] = field(default_factory=dict)
    type = "matrix"

    def take(self, idx):
        idx = np.asarray(idx, dtype=int)
        return replace(self, items=self.items.take(idx), m=self.m[np.ix_(idx, idx)],
                       extra={k: v[np.ix_(idx, idx)] for k, v in self.extra.items()})

    def describe(self) -> str:
        return f"{len(self.items)} × {len(self.items)}"


class Distances(Matrix):
    type = "dist"


class Similarities(Matrix):
    type = "sim"


class Graph(Matrix):
    """Weights ≥ 0, no NaN, zero diagonal."""
    type = "graph"

    def describe(self) -> str:
        edges = int(np.count_nonzero(np.triu(self.m, 1)))
        return f"{len(self.items)} viršūnių, {edges} briaunų"


@dataclass
class Spectrum:
    items: Items
    values: np.ndarray
    vectors: np.ndarray
    graph: Graph
    label: str = ""
    type = "spectrum"

    def take(self, idx):
        raise ValueError("Spektro negalima apriboti: apribokite grafą prieš skaičiuodami spektrą.")

    def describe(self) -> str:
        return f"{len(self.values)} savųjų reikšmių"


@dataclass
class Partition:
    """Group of every unit (None – unknown); ``names``: group → name shown."""
    items: Items
    labels: list[str | None]
    names: dict[str, str] = field(default_factory=dict)
    label: str = ""
    meta: dict[str, Any] = field(default_factory=dict)
    type = "partition"

    def take(self, idx):
        return replace(self, items=self.items.take(idx), labels=[self.labels[int(i)] for i in idx])

    def groups(self) -> list[str]:
        """Groups, largest first."""
        count: dict[str, int] = {}
        for g in self.labels:
            if g is not None:
                count[g] = count.get(g, 0) + 1
        return sorted(count, key=lambda g: (-count[g], str(g)))

    def name(self, g: str | None) -> str:
        return "—" if g is None else self.names.get(g, str(g))

    def describe(self) -> str:
        return f"{len(self.groups())} grupės(-ių)"


@dataclass
class Layout:
    items: Items
    xy: np.ndarray
    label: str = ""
    type = "layout"

    def take(self, idx):
        idx = np.asarray(idx, dtype=int)
        return replace(self, items=self.items.take(idx), xy=self.xy[idx])

    def describe(self) -> str:
        return f"{len(self.items)} taškų"


@dataclass
class Tree:
    """Average-linkage merges [a, b, height, size]; leaves are 0 … n-1, merge i makes node n + i."""
    items: Items
    merges: list[list[float]]
    label: str = ""
    type = "tree"

    def take(self, idx):
        raise ValueError("Medžio negalima apriboti: apribokite atstumus prieš statydami medį.")

    def describe(self) -> str:
        return f"{len(self.items)} lapų"


@dataclass
class Scores:
    """Numeric columns per unit (NaN – unknown); ``meta[col]``: {"label", "up" (True: more is more stable / better,
    False: less is, None: neither), "side", "explain"}."""
    items: Items
    cols: dict[str, np.ndarray]
    meta: dict[str, dict[str, Any]] = field(default_factory=dict)
    label: str = ""
    type = "scores"

    def take(self, idx):
        idx = np.asarray(idx, dtype=int)
        return replace(self, items=self.items.take(idx), cols={k: v[idx] for k, v in self.cols.items()})

    def describe(self) -> str:
        return f"{len(self.cols)} rodikliai(-ių), {len(self.items)} vienetų"


@dataclass
class Basket:
    nodes: list[dict[str, Any]]
    type = "basket"

    def describe(self) -> str:
        return f"{len(self.nodes)} mazgų"


def align(*objs) -> tuple[list[str], list[np.ndarray]]:
    """Units present in all the inputs, in the order of the first: (keys, index of every key in every input)."""
    maps = [{k: i for i, k in enumerate(o.items.keys())} for o in objs]
    keys = [k for k in objs[0].items.keys() if all(k in m for m in maps)]
    return keys, [np.array([m[k] for k in keys], dtype=int) for m in maps]


def common(*objs, need: int = 2, what: str = "") -> list:
    """The inputs restricted to their common units, in one order."""
    keys, idx = align(*objs)
    if len(keys) < need:
        raise ValueError(f"Įėjimai turi per mažai bendrų vienetų ({len(keys)}){what}: ar jie iš tų pačių vienetų?")
    return [o if len(ix) == len(o.items) and np.all(ix == np.arange(len(ix))) else o.take(ix) for o, ix in zip(objs, idx)]


def attribute(items: Items, name: str) -> list[Any]:
    """A unit attribute; ``_<name>_key`` (when there is one) identifies the value, the attribute is its name."""
    if not any(name in r or f"_{name}_key" in r for r in items.rows):
        have = sorted({k for r in items.rows for k in r if not k.startswith("_") and k not in ("key", "name")})
        raise ValueError(f"Vienetai neturi požymio „{name}“. Galimi: {', '.join(have) or 'nėra'}.")
    return [r.get(f"_{name}_key", r.get(name)) for r in items.rows]


# ---------------------------------------------------------------- parts
@dataclass
class Port:
    name: str
    types: tuple[str, ...]
    label: str = ""
    optional: bool = False
    help: str = ""


@dataclass
class Param:
    name: str
    label: str
    type: str = "number"            # number | bool | select | text
    default: Any = None
    min: float | None = None
    max: float | None = None
    options: list[tuple[str, str]] = field(default_factory=list)
    hint: str = ""
    help: str = ""

    def clean(self, value: Any) -> Any:
        if self.type == "bool":
            return bool(value) if value is not None else bool(self.default)
        if self.type == "select":
            return value if value in [o[0] for o in self.options] else self.default
        if self.type == "text":
            return str(value)[:400] if value not in (None, "") else self.default
        if value in (None, ""):
            return self.default
        try:
            x = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"„{self.label}“: ne skaičius ({value!r})") from None
        if not np.isfinite(x) or (self.min is not None and x < self.min) or (self.max is not None and x > self.max):
            raise ValueError(f"„{self.label}“ turi būti tarp {self.min:g} ir {self.max:g}")
        return int(x) if float(x).is_integer() and (self.min is None or float(self.min).is_integer()) else x


@dataclass
class Part:
    id: str
    group: str
    title: str
    summary: str
    fn: Callable[..., Any]
    inputs: list[Port]
    outputs: list[Port]
    params: list[Param]
    help: str = ""
    view: bool = False
    datasets: tuple[str, ...] = ()     # read besides what its queries show (files, e.g. CLTS): for the bibliography

    def describe(self) -> dict[str, Any]:
        return {"id": self.id, "group": self.group, "title": self.title, "summary": self.summary, "help": self.help,
                "view": self.view,
                "inputs": [{"name": p.name, "types": list(p.types), "label": p.label or TYPES.get(p.types[0], ("",))[0],
                            "optional": p.optional, "help": p.help} for p in self.inputs],
                "outputs": [{"name": p.name, "types": list(p.types), "label": p.label or TYPES.get(p.types[0], ("",))[0],
                             "help": p.help} for p in self.outputs],
                "params": [{k: v for k, v in vars(p).items()} | {"options": [list(o) for o in p.options]} for p in self.params]}


PARTS: dict[str, Part] = {}


def part(id: str, group: str, title: str, summary: str, inputs=(), outputs=(), params=(), help: str = "", view: bool = False,
         datasets: tuple[str, ...] = ()):
    """Registers a part; see the module's description."""
    assert group in GROUPS, group

    def wrap(fn):
        assert id not in PARTS, id
        PARTS[id] = Part(id, group, title, summary, fn, list(inputs), list(outputs), list(params), help, view, tuple(datasets))
        return fn
    return wrap


def catalog() -> dict[str, Any]:
    return {"types": {k: {"name": n, "explain": e} for k, (n, e) in TYPES.items()}, "groups": GROUPS,
            "parts": [p.describe() for p in sorted(PARTS.values(), key=lambda p: GROUPS.index(p.group))]}


# ---------------------------------------------------------------- running a setup
class Ctx:
    """What a part gets besides its inputs: the database, the basket, dataset folders, and where to report."""

    def __init__(self, read, nodes, dataset_paths, progress):
        self.read, self.nodes, self.dataset_paths, self._progress = read, nodes, dataset_paths, progress
        self.title = ""
        self.dropped: list[dict[str, Any]] = []
        self.notes: list[str] = []

    def progress(self, message: str) -> None:
        self._progress(f"{self.title}: {message}" if self.title else message)

    def drop(self, row: dict[str, Any], reason: str, detail: str = "") -> None:
        """A unit left out by this part, and why (shown under „Kas neįtraukta“)."""
        self.dropped.append({"key": row.get("key"), "name": row.get("name") or row.get("key"), "reason": reason, "detail": detail})

    def note(self, text: str) -> None:
        self.notes.append(text)


MAX_BLOCKS, MAX_LINKS = 80, 240
_cache: OrderedDict[str, tuple[float, Any]] = OrderedDict()
_cache_lock = threading.Lock()
CACHE_SIZE, CACHE_SECONDS = 48, 30 * 60


def _cache_get(key: str):
    with _cache_lock:
        hit = _cache.get(key)
        if hit is None or time.time() - hit[0] > CACHE_SECONDS:
            _cache.pop(key, None)
            return None
        _cache.move_to_end(key)
        return hit[1]


def _cache_put(key: str, value) -> None:
    with _cache_lock:
        _cache[key] = (time.time(), value)
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def check_setup(setup: Any) -> dict[str, Any]:
    """The setup as sent by the page, checked: known parts, ports and types, no cycles. Unknown parameters are dropped."""
    if not isinstance(setup, dict) or not isinstance(setup.get("blocks"), list):
        raise ValueError("Sąranka tuščia: nutempkite detales į dirbtuves ir sujunkite jas.")
    blocks, links = setup["blocks"], setup.get("links") or []
    if len(blocks) > MAX_BLOCKS or len(links) > MAX_LINKS:
        raise ValueError(f"Sąranka per didelė (daugiausia {MAX_BLOCKS} detalių ir {MAX_LINKS} jungčių).")
    out_blocks, ids = [], set()
    for b in blocks:
        if not isinstance(b, dict) or b.get("type") not in PARTS:
            raise ValueError(f"Nežinoma detalė: {b.get('type') if isinstance(b, dict) else b!r}")
        bid = str(b.get("id") or "")
        if not bid or bid in ids or len(bid) > 40:
            raise ValueError("Detalių žymės turi būti skirtingos.")
        ids.add(bid)
        p = PARTS[b["type"]]
        given = b.get("params") if isinstance(b.get("params"), dict) else {}
        out_blocks.append({"id": bid, "type": p.id, "params": {q.name: given.get(q.name, q.default) for q in p.params},
                           "x": float(b.get("x") or 0), "y": float(b.get("y") or 0), "note": str(b.get("note") or "")[:200]})
    by_id = {b["id"]: b for b in out_blocks}
    out_links, taken = [], set()
    for ln in links:
        try:
            (fb, fp), (tb, tp) = ln["from"], ln["to"]
        except (KeyError, TypeError, ValueError):
            raise ValueError("Netinkama jungtis.") from None
        if fb not in by_id or tb not in by_id:
            raise ValueError("Jungtis į nesamą detalę.")
        src, dst = PARTS[by_id[fb]["type"]], PARTS[by_id[tb]["type"]]
        out = next((o for o in src.outputs if o.name == fp), None)
        inp = next((i for i in dst.inputs if i.name == tp), None)
        if out is None or inp is None:
            raise ValueError(f"„{src.title}“ → „{dst.title}“: nėra tokio lizdo.")
        if (tb, tp) in taken:
            raise ValueError(f"„{dst.title}“: į vieną įėjimą jungiama tik viena jungtis.")
        taken.add((tb, tp))
        out_links.append({"from": [fb, fp], "to": [tb, tp]})
    order(out_blocks, out_links)
    return {"blocks": out_blocks, "links": out_links}


def order(blocks: list[dict[str, Any]], links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Blocks so that every one comes after those it takes inputs from (top to bottom, left to right among equals)."""
    deps = {b["id"]: {ln["from"][0] for ln in links if ln["to"][0] == b["id"]} for b in blocks}
    done: list[dict[str, Any]] = []
    left = sorted(blocks, key=lambda b: (b["y"], b["x"]))
    while left:
        ready = [b for b in left if deps[b["id"]] <= {d["id"] for d in done}]
        if not ready:
            raise ValueError("Sąrankoje yra uždaras ratas: detalė negali gauti savo pačios rezultato.")
        done.append(ready[0])
        left.remove(ready[0])
    return done


def _type_ok(value, port: Port) -> bool:
    if ANY in port.types:
        return hasattr(value, "items")
    return getattr(value, "type", None) in port.types


def execute(read, nodes, setup: dict[str, Any], dataset_paths, progress: Callable[[str], None] = lambda m: None) -> dict[str, Any]:
    """Runs a checked setup. A block that fails does not stop the others: the blocks that need its result are skipped,
    the rest still give their fruits.

    When ``read`` follows the datasets it reads (``kalba_sodas.sekimas.Tracker.wrap``), every block follows its own:
    the block's state names them (``datasets``), also when its result comes from the cache."""
    blocks = order(setup["blocks"], setup["links"])
    if not any(PARTS[b["type"]].view for b in blocks):
        raise ValueError("Sąrankoje nėra nė vieno vaisiaus: pridėkite detalę iš grupės „Vaisiai“ ir prijunkite ją.")
    feeds = {(ln["to"][0], ln["to"][1]): tuple(ln["from"]) for ln in setup["links"]}
    values: dict[tuple[str, str], Any] = {}
    hashes: dict[str, str] = {}
    status: dict[str, dict[str, Any]] = {}
    fruits, dropped = [], []
    basket = [{k: n.get(k) for k in ("label", "key", "display_name")} for n in nodes]
    tracker = getattr(read, "tracker", None)
    for step, b in enumerate(blocks, 1):
        p = PARTS[b["type"]]
        own = tracker.child() if tracker is not None else None
        ctx = Ctx(own.wrap(read) if own is not None else read, nodes, dataset_paths, progress)
        ctx.title = p.title
        progress(f"{p.title} ({step}/{len(blocks)})…")
        t0 = time.time()
        inputs, missing, upstream_failed, wrong = {}, [], [], []
        for port in p.inputs:
            src = feeds.get((b["id"], port.name))
            if src is None:
                if not port.optional:
                    missing.append(port.label or TYPES[port.types[0]][0])
                continue
            if src not in values:
                upstream_failed.append(src[0])
                continue
            v = values[src]
            if not _type_ok(v, port):
                wrong.append(f"„{port.label or port.name}“ laukia {' / '.join(TYPES[t][0] for t in port.types if t in TYPES) or 'vienetų'}, "
                             f"o gauna {TYPES.get(getattr(v, 'type', ''), ('?',))[0]}")
                continue
            inputs[port.name] = v
        if missing or upstream_failed or wrong:
            parts = ([f"Neprijungta: {', '.join(missing)}."] if missing else []) + [f"{w}." for w in wrong]
            status[b["id"]] = {"status": "skipped" if upstream_failed and not missing and not wrong else "error",
                               "error": " ".join(parts) or "Laukia detalės, kuri nepavyko."}
            continue
        try:
            params = {q.name: q.clean(b["params"].get(q.name)) for q in p.params}
        except ValueError as exc:
            status[b["id"]] = {"status": "error", "error": str(exc)}
            continue
        key = hashlib.sha1(json.dumps([p.id, params, {q: hashes[s[0]] + "/" + s[1] for (bid, q), s in feeds.items() if bid == b["id"] and s[0] in hashes},
                                       basket if p.id == "krepsys" else None], sort_keys=True, default=str).encode()).hexdigest()
        hashes[b["id"]] = key
        hit = _cache_get(key)
        try:
            if hit is not None:
                out, ctx.dropped, ctx.notes, used = hit
            else:
                out = p.fn(ctx, inputs, params) or {}
                used = sorted(own.found) if own is not None else []
                _cache_put(key, (out, ctx.dropped, ctx.notes, used))
        except ValueError as exc:
            status[b["id"]] = {"status": "error", "error": str(exc)}
            continue
        except Exception as exc:  # noqa: BLE001 – shown on the block; the rest of the setup still runs
            status[b["id"]] = {"status": "error", "error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc(limit=5)}
            continue
        st = {"status": "ok", "seconds": round(time.time() - t0, 2), "cached": hit is not None}
        if own is not None:
            used = sorted(set(used) | set(p.datasets))
            tracker.add(*used)
            if used:
                st["datasets"] = used
        if p.view:
            fruit = jsonable({**out, "block": b["id"], "part": p.id, "title": b.get("note") or p.title})
            fruit.setdefault("notes", [])
            fruit["notes"] = [{"title": "", "text": t} for t in ctx.notes] + fruit["notes"]
            fruits.append(fruit)
            st["summary"] = "vaisius paruoštas"
        else:
            for port in p.outputs:
                if port.name in out:
                    values[(b["id"], port.name)] = out[port.name]
            st["summary"] = "; ".join(v.describe() for v in out.values() if hasattr(v, "describe"))
            if ctx.notes:
                st["notes"] = ctx.notes
        if ctx.dropped:
            st["dropped"] = len(ctx.dropped)
            dropped += [{**d, "block": b["id"], "part": p.title} for d in ctx.dropped]
        status[b["id"]] = st
    place = {b["id"]: (b["y"], b["x"]) for b in blocks}
    fruits.sort(key=lambda f: place[f["block"]])
    errors = sum(1 for s in status.values() if s["status"] != "ok")
    return {"setup": setup, "blocks": status, "fruits": fruits, "dropped": jsonable(dropped[:5000]),
            "summary": {"blocks": len(blocks), "fruits": len(fruits), "errors": errors,
                        "views": sum(1 for b in blocks if PARTS[b["type"]].view)}}


def jsonable(o: Any) -> Any:
    """Plain JSON: numpy numbers and arrays become numbers and lists, NaN and ±∞ become null."""
    if isinstance(o, dict):
        return {str(k): jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jsonable(v) for v in o]
    if isinstance(o, np.ndarray):
        return jsonable(o.tolist())
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        return float(o) if np.isfinite(o) else None
    if isinstance(o, (set, frozenset)):
        return [jsonable(v) for v in sorted(o, key=str)]
    return o


# attribute → its name on the page
ATTR_LABELS = {"name": "vienetas", "language": "kalba", "cognate": "kognatų grupė", "dataset": "duomenynas", "reconstructed": "rekonstruota",
               "glottolog_name": "Glottolog kalba", "lat": "platuma", "lon": "ilguma", "segments": "segmentai",
               "segment_source": "segmentų šaltinis", "meanings": "koduotų reikšmių", "field": "semantinis laukas", "focus": "krepšyje",
               "languages": "kalbų", "count": "vienetų", "concepticon": "Concepticon"}


def public_row(r: dict[str, Any]) -> dict[str, Any]:
    """A unit for the page: without the parts' own (``_``) attributes, except its node label."""
    out = {k: v for k, v in r.items() if not k.startswith("_")}
    if r.get("_label"):
        out["label"] = r["_label"]
    return out
