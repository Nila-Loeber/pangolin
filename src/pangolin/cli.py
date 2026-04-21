"""Pangolin CLI — `pangolin init|cycle|run|harden-egress|refresh-workflows|version`."""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pangolin",
        description="Owner-triggered conversational cycles for wiki repos.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    init_p = sub.add_parser(
        "init",
        help="Scaffold pangolin config files into the current repo.",
    )
    init_p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing files instead of skipping them.",
    )
    init_p.add_argument(
        "--with-wiki",
        action="store_true",
        help="Also seed wiki/ with index.md, log.md, and ref/project/draft/ directories.",
    )

    sub.add_parser(
        "refresh-workflows",
        help="Overwrite .github/workflows/*.yml from package defaults. "
             "Use after bumping the installed pangolin package to pick up "
             "new workflow-shim changes without rewriting wiki content.",
    )
    sub.add_parser(
        "cycle",
        help="Harden egress and run one full conversational cycle. "
             "Equivalent to `pangolin harden-egress && pangolin run` but in "
             "a single process — the recommended entry point for the "
             "agent-cycle workflow so the shim never has to split steps.",
    )
    sub.add_parser("run", help="Run one full conversational cycle (includes one software task if queued).")
    sub.add_parser(
        "harden-egress",
        help="Bring up the egress proxy + lock host egress via iptables. "
             "Workflow step before `pangolin run`. Prefer `pangolin cycle` "
             "which does both in one step.",
    )
    sub.add_parser("version", help="Print the installed version.")

    args = parser.parse_args(argv)

    if args.cmd == "init":
        from pangolin.scaffold import init_repo
        return init_repo(force=args.force, with_wiki=args.with_wiki)
    if args.cmd == "refresh-workflows":
        from pangolin.scaffold import refresh_workflows
        return refresh_workflows()
    if args.cmd == "cycle":
        from pangolin.orchestrate import harden_egress, run_cycle
        harden_egress()
        run_cycle()
        return 0
    if args.cmd == "run":
        from pangolin.orchestrate import run_cycle
        run_cycle()
        return 0
    if args.cmd == "harden-egress":
        from pangolin.orchestrate import harden_egress
        harden_egress()
        return 0
    if args.cmd == "version":
        from pangolin import __version__
        print(__version__)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
