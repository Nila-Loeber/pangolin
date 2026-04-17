"""Sandburg CLI — `sandburg init|run|software|version`."""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sandburg",
        description="Owner-triggered conversational cycles for wiki repos.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    init_p = sub.add_parser(
        "init",
        help="Scaffold sandburg config files into the current repo.",
    )
    init_p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing files instead of skipping them.",
    )

    sub.add_parser("run", help="Run one full conversational cycle.")
    sub.add_parser("software", help="Run one software-mode task.")
    sub.add_parser("version", help="Print the installed version.")

    args = parser.parse_args(argv)

    if args.cmd == "init":
        from sandburg.scaffold import init_repo
        return init_repo(force=args.force)
    if args.cmd == "run":
        from sandburg.orchestrate import run_cycle
        run_cycle()
        return 0
    if args.cmd == "software":
        from sandburg.software import run as run_software
        run_software()
        return 0
    if args.cmd == "version":
        from sandburg import __version__
        print(__version__)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
