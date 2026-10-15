"""Vaivos dirbtuvės: a spectral study put together from parts in the browser (see ``core``).

To Vaiva it is one more study (``STUDY``, ``run``): its parameter is the setup; its result – the fruits of the setup's
view parts, the state of every block and the units left out.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from . import grafai, matai, rodikliai, saltiniai, sietai, spektras, vaisiai  # noqa: F401 – they register their parts
from .core import PARTS, catalog, check_setup, execute
from .receptai import RECIPES

STUDY = {
    "id": "dirbtuves",
    "title": "Vaivos dirbtuvės",
    "summary": "Spektrinės analizės tyrimas, surinktas iš detalių: šaltinių, matų, grafų, sietų, spektrinės analizės, "
               "rodiklių ir vaisių.",
    "accepts": ["Concept", "Sense", "Lexeme", "Form", "CognateSet", "Languoid"],
    "basket_optional": True,
    "workshop": True,
    "params": [],
}


def run(read: Callable[..., list[Any]], nodes: list[dict[str, Any]], params: dict[str, Any],
        dataset_paths: dict[str, Path], progress: Callable[[str], None] = lambda m: None) -> dict[str, Any]:
    setup = check_setup(params.get("setup"))
    result = execute(read, nodes, setup, dataset_paths, progress)
    return {"study": STUDY["id"], "title": params.get("title") or STUDY["title"], **result}


def workshop() -> dict[str, Any]:
    """What the page needs to draw the workshop: data types, parts, ready setups."""
    return {**catalog(), "recipes": RECIPES}


__all__ = ["PARTS", "RECIPES", "STUDY", "check_setup", "run", "workshop"]
