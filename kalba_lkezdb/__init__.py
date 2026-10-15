"""LKEŽDB (Lietuvių kalbos etimologinio žodyno duomenų bazė) → Sodo Neo4j grafas per kalbos modelį.

Duomenų talpykla: ``duomenynai/lkezdb/puslapiai.db`` (nuskaityti žodžiai, puslapiai, straipsniai, šaltiniai,
aiškinimai, darbų eilė, variklio nustatymai)."""
from pathlib import Path

DEFAULT_DB = Path("duomenynai") / "lkezdb" / "puslapiai.db"
