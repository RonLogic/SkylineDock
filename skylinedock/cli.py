from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from .installer import InstallError, build_install_plan, install
from .scanner import ArchiveScanner
from .source_builder import (
    SourceBuildError,
    build_trusted_source,
    check_source_build_prerequisites,
    inspect_source_build,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="skylinedock")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_parser = subparsers.add_parser("scan", help="Inspect a package without installing it")
    scan_parser.add_argument("path", type=Path)
    scan_parser.add_argument("--json", action="store_true", dest="as_json")

    plan_parser = subparsers.add_parser("plan", help="Show the destination for an installable package")
    plan_parser.add_argument("path", type=Path)
    plan_parser.add_argument("--app-data", type=Path)

    install_parser = subparsers.add_parser("install", help="Install a package transactionally")
    install_parser.add_argument("path", type=Path)
    install_parser.add_argument("--app-data", type=Path)
    install_parser.add_argument("--yes", action="store_true", help="Confirm the write operation")

    source_check_parser = subparsers.add_parser(
        "source-check", help="Inspect source-build requirements without executing them"
    )
    source_check_parser.add_argument("path", type=Path)
    source_check_parser.add_argument("--steam-root", type=Path)
    source_check_parser.add_argument("--game-path", type=Path)

    source_build_parser = subparsers.add_parser(
        "build-source", help="Build trusted source, validate it, and install the result"
    )
    source_build_parser.add_argument("path", type=Path)
    source_build_parser.add_argument("--app-data", type=Path)
    source_build_parser.add_argument("--game-path", type=Path)
    source_build_parser.add_argument(
        "--trust-source-code",
        action="store_true",
        help="Acknowledge that project build scripts will execute with your user permissions",
    )

    args = parser.parse_args(argv)
    report = ArchiveScanner().scan(args.path)

    if args.command in {"source-check", "build-source"}:
        try:
            inspection = inspect_source_build(report)
            prerequisites = check_source_build_prerequisites(
                inspection,
                getattr(args, "steam_root", None),
                getattr(args, "game_path", None),
            )
            if args.command == "source-check":
                print(f"Mod: {inspection.mod_name}")
                print(f"Solution: {inspection.solution_file}")
                print(f"Required .NET SDK: {inspection.dotnet_sdk_version or 'not declared'}")
                for warning in inspection.warnings:
                    print(f"WARNING: {warning}")
                for issue in prerequisites.issues:
                    print(f"MISSING: {issue}")
                return 0 if prerequisites.ready else 2

            if not args.trust_source_code:
                print(
                    "ERROR: Source build was not started. Re-run with --trust-source-code only "
                    "after reviewing and trusting the source."
                )
                return 3
            with tempfile.TemporaryDirectory(prefix="SkylineDock-build-") as temporary:
                result = build_trusted_source(
                    report,
                    temporary,
                    trusted_source_confirmed=True,
                    prerequisites=prerequisites,
                )
                plan = build_install_plan(result.compiled_report, args.app_data)
                installed = install(plan)
            print(f"Built and installed: {installed}")
            return 0
        except (SourceBuildError, InstallError) as exc:
            print(f"ERROR: {exc}")
            return 2

    if args.command == "scan":
        if args.as_json:
            print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(f"{report.display_name}: {report.kind.value}")
            print(report.recommended_action)
            if report.metadata.paradox_url:
                print(report.metadata.paradox_url)
            for error in report.errors:
                print(f"ERROR: {error}")
        return 0 if not report.errors else 2

    try:
        plan = build_install_plan(report, getattr(args, "app_data", None))
        print(plan.destination)
        if args.command == "plan":
            return 0
        if not args.yes:
            print("Installation was not performed. Re-run with --yes after reviewing the destination.")
            return 3
        installed = install(plan)
        print(f"Installed: {installed}")
        return 0
    except InstallError as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
