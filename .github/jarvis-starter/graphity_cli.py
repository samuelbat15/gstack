from __future__ import annotations

import argparse
from pathlib import Path

from graphity_runtime import GraphityRuntime, GraphityStateError


def parse_split(values: list[str]) -> dict[str, int]:
    targets: dict[str, int] = {}
    for value in values:
        if "=" not in value:
            raise GraphityStateError(f"Format invalide: {value}. Utilise revision=percent.")
        key, raw_percent = value.split("=", 1)
        targets[key.strip()] = int(raw_percent.strip())
    return targets


def build_runtime(args: argparse.Namespace) -> GraphityRuntime:
    return GraphityRuntime(Path(args.data_dir))


def main() -> int:
    parser = argparse.ArgumentParser(description="Graphity local runtime for Jarvis.")
    parser.add_argument("--data-dir", default="./data/graphity", help="Dossier d'etat Graphity.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Cree les revisions locales par defaut.")
    sub.add_parser("list", help="Liste les revisions.")
    sub.add_parser("traffic", help="Affiche le routage actuel.")
    sub.add_parser("always-latest", help="Route 100% vers la derniere revision.")

    revision = sub.add_parser("revision", help="Cree une nouvelle revision locale.")
    revision.add_argument("--label", required=True)
    revision.add_argument("--kind", default="graph")
    revision.add_argument("--instructions", required=True)

    split = sub.add_parser("split", help="Configure un split manuel, ex: 1=50 2=50.")
    split.add_argument("targets", nargs="+")

    recall = sub.add_parser("recall", help="Rappelle la memoire graphe locale.")
    recall.add_argument("query")

    args = parser.parse_args()
    runtime = build_runtime(args)

    try:
        if args.command == "init":
            runtime.ensure_bootstrap()
            print("Graphity initialise.")
        elif args.command == "list":
            for item in runtime.list_revisions():
                print(f"{item['number']}: {item['label']} [{item['agent_kind']}] {item['name']}")
        elif args.command == "traffic":
            print(runtime.describe_traffic())
        elif args.command == "always-latest":
            runtime.set_always_latest()
            print(runtime.describe_traffic())
        elif args.command == "revision":
            item = runtime.create_revision(args.label, args.kind, args.instructions)
            print(f"Revision creee: {item['label']} -> {item['name']}")
        elif args.command == "split":
            runtime.set_manual_split(parse_split(args.targets))
            print(runtime.describe_traffic())
        elif args.command == "recall":
            print(runtime.memory.recent_context(args.query) or "Aucune memoire.")
    except GraphityStateError as exc:
        print(f"Erreur Graphity: {exc}")
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
