"""Downloading the datasets: each one is a fixed release of a public repository, fetched as a GitHub archive.

The versions are the ones Sodas was built and tested with (the importer's profiles fit them). Nothing else is needed –
no ``git``: the archive of one commit is streamed to disk, checked and unpacked into the folder ``datasets.yaml`` names.
A file ``.sodas-saltinis.json`` in that folder tells what was downloaded and when.

The data are not part of Sodas: every dataset keeps its own licence (most are CC BY 4.0, D-PLACE and NoRaRe are
CC BY-NC 4.0 – not for commercial use). Cite the datasets you use.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .import_all import IMPORT_ORDER, read_datasets_config

MARKER = ".sodas-saltinis.json"
USER_AGENT = "Sodas (dataset downloader)"


@dataclass(frozen=True)
class Source:
    dataset_id: str
    repo: str          # owner/name on GitHub
    commit: str        # the exact commit Sodas was tested with
    version: str       # its release tag (or the nearest one)
    folder: str        # default folder under duomenynai/
    license: str
    size_mb: int       # unpacked, roughly
    url: str = ""      # the dataset's home page

    @property
    def archive(self) -> str:
        return f"https://codeload.github.com/{self.repo}/zip/{self.commit}"

    @property
    def page(self) -> str:
        return self.url or f"https://github.com/{self.repo}"


CC_BY = "CC BY 4.0"
CC_BY_NC = "CC BY-NC 4.0"
CATALOG: dict[str, Source] = {s.dataset_id: s for s in [
    Source("glottolog", "glottolog/glottolog", "8fdbc6f1347328f0bdb3333f7cf8a6fffe586ced", "v5.3", "glottolog", CC_BY, 560,
           "https://glottolog.org"),
    Source("concepticon", "concepticon/concepticon-data", "a89063d5657022a4ac11c557baef4958809e7c91", "v3.4.0", "concepticon-data",
           CC_BY, 21, "https://concepticon.clld.org"),
    Source("clts", "cldf-clts/clts", "4da03b1d0bc2c96839df693d3123be72cfac8419", "v2.3.0", "clts", CC_BY, 51, "https://clts.clld.org"),
    Source("iecor", "lexibank/iecor", "700b635a04786427b78841489c46eefbe2843509", "v1.2", "iecor", CC_BY, 26, "https://iecor.clld.org"),
    Source("wold", "lexibank/wold", "1df62b9bdc7292b35982aea49b4d5bd1951f6f3e", "v4.2", "wold", CC_BY, 65, "https://wold.clld.org"),
    Source("lexibank_analysed", "lexibank/lexibank-analysed", "edf5f028de7eabdabe0998a4a831e5e7dca79117", "v2.2.6",
           "lexibank-analysed", CC_BY, 137),
    Source("clics4", "clics/clics4", "1ddece619d026d7fc11a4dcab3fa71ecd059efe7", "v1.0", "clics4", CC_BY, 110, "https://clics.clld.org"),
    Source("norare", "concepticon/norare-data", "e2ba7fd4e5e5d7365b8805dbbf8d99ed53b4ebad", "v1.1", "norare-data", CC_BY_NC, 58,
           "https://norare.clld.org"),
    Source("phoible", "cldf-datasets/phoible", "5c477f1934f57b3c1a16168fadc08e83dbc03362", "v2.0.1", "phoible", CC_BY, 12,
           "https://phoible.org"),
    Source("wals", "cldf-datasets/wals", "f97440d6edbaed0097d1bd307a5a20ea3f09e271", "v2020.5", "wals", CC_BY, 47, "https://wals.info"),
    Source("grambank", "grambank/grambank", "37f73da55cf8b426c82383f46a972bc59ce6cf76", "v1.0.3", "grambank", CC_BY, 57,
           "https://grambank.clld.org"),
    Source("dplace", "D-PLACE/dplace-cldf", "d82fbb6e955d3b33317b80ddc49455fe8a8b1b68", "v3.2.0", "dplace-cldf", CC_BY_NC, 78,
           "https://d-place.org"),
    Source("asjp", "lexibank/asjp", "cf4bf0d13c95256b1b48f440d07c5c098500a770", "v21.1", "asjp", CC_BY, 76, "https://asjp.clld.org"),
    Source("datsemshift", "lexibank/datsemshift", "783be8651466abebeff53b8a7308d807f0e0e9d9", "v1.1rc", "datsemshift", CC_BY, 21,
           "https://datsemshift.ru"),
]}
assert set(CATALOG) == set(IMPORT_ORDER), "every importable dataset needs a download source"


def target_for(dataset_id: str, config: Path) -> Path:
    """Where the dataset goes: the path ``datasets.yaml`` gives it, else ``duomenynai/<folder>`` beside that file."""
    paths = read_datasets_config(config) if config.exists() else {}
    return paths.get(dataset_id) or (config.parent / "duomenynai" / CATALOG[dataset_id].folder).resolve()


def installed(path: Path) -> dict | None:
    """What a download wrote into the folder (None: not downloaded by Sodas, maybe a git clone of one's own)."""
    try:
        return json.loads((path / MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _safe_members(zf: zipfile.ZipFile, dest: Path) -> list[zipfile.ZipInfo]:
    root = dest.resolve()
    out = []
    for m in zf.infolist():
        p = (dest / m.filename).resolve()
        if root != p and root not in p.parents:
            raise ValueError(f"archyve netinkamas kelias: {m.filename}")
        out.append(m)
    return out


def download(dataset_id: str, config: Path, progress: Callable[[str], None] = print, replace: bool = False,
             opener: Callable = urllib.request.urlopen) -> dict:
    """Fetch one dataset into its folder. An existing folder is kept unless ``replace`` (then it is swapped out only
    after the new copy is complete, so a broken download never leaves a half-empty folder)."""
    src = CATALOG.get(dataset_id)
    if src is None:
        raise ValueError(f"nežinomas duomenynas: {dataset_id}")
    target = target_for(dataset_id, config)
    if target.exists() and any(target.iterdir()) and not replace:
        progress(f"{dataset_id}: jau yra ({target}) – praleidžiama")
        return {"dataset": dataset_id, "status": "skipped", "path": str(target)}
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent, prefix=f".{target.name}-") as tmp:
        tmp_path = Path(tmp)
        archive = tmp_path / "archive.zip"
        progress(f"{dataset_id}: siunčiama {src.repo} {src.version} (~{src.size_mb} MB išskleidus)")
        req = urllib.request.Request(src.archive, headers={"User-Agent": USER_AGENT})
        got, step = 0, 20 * 1024 * 1024
        with opener(req, timeout=60) as resp, open(archive, "wb") as fh:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
                got += len(chunk)
                if got // step != (got - len(chunk)) // step:
                    progress(f"{dataset_id}: atsiųsta {got // (1024 * 1024)} MB")
        progress(f"{dataset_id}: atsiųsta {got / 1024 / 1024:.1f} MB, išskleidžiama…")
        unpacked = tmp_path / "unpacked"
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(unpacked, members=_safe_members(zf, unpacked))
        archive.unlink()
        tops = [p for p in unpacked.iterdir()]
        content = tops[0] if len(tops) == 1 and tops[0].is_dir() else unpacked   # GitHub wraps it in <repo>-<commit>/
        (content / MARKER).write_text(json.dumps({
            "dataset": dataset_id, "repo": src.repo, "commit": src.commit, "version": src.version, "license": src.license,
            "archive": src.archive, "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        old = None
        if target.exists():
            old = tmp_path / "old"
            target.rename(old)
        content.rename(target)
        if old is not None:
            shutil.rmtree(old, ignore_errors=True)
    progress(f"{dataset_id}: paruošta → {target} (licencija {src.license})")
    return {"dataset": dataset_id, "status": "downloaded", "path": str(target), "version": src.version}


def download_many(dataset_ids: list[str], config: Path, progress: Callable[[str], None] = print, replace: bool = False) -> dict:
    """Several datasets in the importer's order; one failing does not stop the others."""
    results, failed = [], []
    for dataset_id in [d for d in IMPORT_ORDER if d in set(dataset_ids)]:
        try:
            results.append(download(dataset_id, config, progress, replace=replace))
        except Exception as exc:  # noqa: BLE001 – reported, the rest go on
            progress(f"{dataset_id}: NEPAVYKO – {exc}")
            failed.append(dataset_id)
            results.append({"dataset": dataset_id, "status": "failed", "error": str(exc)})
    return {"status": "failed" if failed else "ok", "results": results, "failed": failed}


def ensure_config(config: Path) -> None:
    """A fresh installation has no ``datasets.yaml`` yet: write one with the default folders."""
    if config.exists():
        return
    lines = ["# Duomenynų katalogai (santykiniai keliai – nuo šios bylos). Atsisiunčiama: Sodas → ⚙ → Duomenynai → Atsisiųsti",
             "datasets:"]
    lines += [f"  {d}: duomenynai/{CATALOG[d].folder}" for d in IMPORT_ORDER]
    config.write_text("\n".join(lines) + "\n", encoding="utf-8")
