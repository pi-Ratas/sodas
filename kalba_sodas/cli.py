from __future__ import annotations

import argparse
from pathlib import Path

from kalba_import.neo4j_config import DEFAULT_NEO4J_CONFIG


def add_serve_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", default="datasets.yaml", help="datasets.yaml for the importer")
    parser.add_argument("--work-dir", default="build/import-all")
    parser.add_argument("--neo4j-config", default=str(DEFAULT_NEO4J_CONFIG))
    parser.add_argument("--data-dir", default="sodas-duomenys", help="settings, gardens, images, Vaiva runs and log of the garden")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--no-browser", action="store_true")


def serve_from_args(args) -> int:
    from .server import serve
    serve(Path(args.config), Path(args.work_dir), Path(args.neo4j_config), Path(args.data_dir), host=args.host,
          port=args.port, batch_size=args.batch_size, open_browser=not args.no_browser)
    return 0


def flags_from_args(args) -> int:
    """``sodas vėliavos``: flags for the languages in Neo4j (the same as the button in the settings)."""
    from kalba_import.neo4j_config import neo4j_settings
    from .flags import assign_flags
    from .graph import Graph
    from .store import Store
    graph = Graph(lambda: neo4j_settings(config_path=Path(args.neo4j_config)))
    r = assign_flags(Store(Path(args.data_dir)), graph.read)
    print(f"Pridėta taisyklių: {len(r['added'])}; užuominų: {r['titled']}" + (f"; nepavyko: {', '.join(r['failed'])}" if r["failed"] else ""))
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else __import__("sys").argv[1:])
    if argv[:1] in (["vėliavos"], ["veliavos"]):
        parser = argparse.ArgumentParser(prog="sodas vėliavos", description="Kalboms su žinoma vėliava priskirti vėliavų paveiksliukus")
        parser.add_argument("--neo4j-config", default=str(DEFAULT_NEO4J_CONFIG))
        parser.add_argument("--data-dir", default="sodas-duomenys")
        return flags_from_args(parser.parse_args(argv[1:]))
    parser = argparse.ArgumentParser(prog="sodas", description="Sodas: žemė (duomenynai), sodas (tyrimai), Vaiva ir nustatymai. "
                                     "„sodas vėliavos“ – kalboms priskirti vėliavas.")
    add_serve_args(parser)
    return serve_from_args(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
