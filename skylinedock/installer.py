from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import uuid
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from .models import PackageKind, ScanReport, SourceType


class InstallError(RuntimeError):
    pass


@dataclass(slots=True)
class InstallPlan:
    report: ScanReport
    app_data_root: Path
    destination_parent: Path
    destination: Path
    package_folder_name: str


def default_cs2_app_data() -> Path:
    user_profile = Path(os.environ.get("USERPROFILE", Path.home()))
    return user_profile / "AppData" / "LocalLow" / "Colossal Order" / "Cities Skylines II"


def build_install_plan(report: ScanReport, app_data_root: str | Path | None = None) -> InstallPlan:
    if not report.can_install:
        raise InstallError("The scanned package is not safe and ready for automatic installation.")

    root = Path(app_data_root).expanduser().resolve() if app_data_root else default_cs2_app_data()
    if report.kind == PackageKind.READY_CODE_MOD:
        parent = root / "Mods"
    elif report.kind == PackageKind.ASSET_PACKAGE:
        parent = root / "ImportedData"
    else:
        raise InstallError(f"Unsupported package type: {report.kind.value}")

    fallback = report.common_root or report.source_path.stem
    if report.kind == PackageKind.READY_CODE_MOD and report.dll_files:
        fallback = report.common_root or Path(report.dll_files[0]).stem
    folder_name = _safe_folder_name(report.metadata.display_name or fallback)

    return InstallPlan(
        report=report,
        app_data_root=root,
        destination_parent=parent,
        destination=parent / folder_name,
        package_folder_name=folder_name,
    )


def install(plan: InstallPlan) -> Path:
    """Install transactionally, backing up an existing package before replacement."""

    if not plan.report.can_install:
        raise InstallError("Installation refused because the package is not installable.")

    plan.destination_parent.mkdir(parents=True, exist_ok=True)
    state_root = plan.app_data_root / ".skylinedock"
    backup_root = state_root / "backups"
    receipt_root = state_root / "receipts"
    backup_root.mkdir(parents=True, exist_ok=True)
    receipt_root.mkdir(parents=True, exist_ok=True)

    staging = Path(tempfile.mkdtemp(prefix=".skylinedock-staging-", dir=plan.destination_parent))
    payload = staging / plan.package_folder_name
    payload.mkdir()
    backup: Path | None = None

    try:
        _copy_payload(plan.report, payload)
        if not any(payload.rglob("*")):
            raise InstallError("The package did not produce any installable files.")

        if plan.destination.exists():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup = backup_root / f"{plan.package_folder_name}-{stamp}-{uuid.uuid4().hex[:8]}"
            os.replace(plan.destination, backup)

        os.replace(payload, plan.destination)
        _write_receipt(plan, backup, receipt_root)
        return plan.destination
    except Exception as exc:
        if plan.destination.exists() and backup is not None:
            shutil.rmtree(plan.destination, ignore_errors=True)
        if backup is not None and backup.exists() and not plan.destination.exists():
            os.replace(backup, plan.destination)
        if isinstance(exc, InstallError):
            raise
        raise InstallError(str(exc)) from exc
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _copy_payload(report: ScanReport, destination: Path) -> None:
    if report.source_type == SourceType.ZIP:
        _copy_zip_payload(report, destination)
    elif report.source_type == SourceType.DIRECTORY:
        _copy_directory_payload(report, destination)
    elif report.source_type == SourceType.DIRECT_FILE:
        shutil.copy2(report.source_path, destination / report.source_path.name)
    else:
        raise InstallError(f"Unsupported source: {report.source_type.value}")


def _copy_zip_payload(report: ScanReport, destination: Path) -> None:
    with zipfile.ZipFile(report.source_path) as archive:
        prefix = f"{report.common_root}/" if report.common_root else ""
        for info in archive.infolist():
            if info.is_dir():
                continue
            normalized = info.filename.replace("\\", "/")
            relative = normalized[len(prefix) :] if prefix and normalized.startswith(prefix) else normalized
            target = _safe_destination(destination, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info, "r") as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def _copy_directory_payload(report: ScanReport, destination: Path) -> None:
    source_root = report.source_path.resolve()
    for source in source_root.rglob("*"):
        if source.is_symlink():
            raise InstallError(f"Symbolic links are not accepted: {source}")
        if not source.is_file():
            continue
        relative = source.relative_to(source_root).as_posix()
        target = _safe_destination(destination, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _safe_destination(root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if not relative or pure.is_absolute() or ".." in pure.parts or re.match(r"^[A-Za-z]:", relative):
        raise InstallError(f"Unsafe package path: {relative}")
    target = (root / Path(*pure.parts)).resolve()
    if not target.is_relative_to(root.resolve()):
        raise InstallError(f"Package path escapes its destination: {relative}")
    return target


def _write_receipt(plan: InstallPlan, backup: Path | None, receipt_root: Path) -> None:
    receipt = {
        "schema_version": 1,
        "installed_at": datetime.now(timezone.utc).isoformat(),
        "source": str(plan.report.source_path),
        "kind": plan.report.kind.value,
        "destination": str(plan.destination),
        "backup": str(backup) if backup else None,
        "metadata": asdict(plan.report.metadata),
    }
    target = receipt_root / f"{plan.package_folder_name}.json"
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(receipt, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, target)


def _safe_folder_name(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", value).strip().strip(".")
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        raise InstallError("Could not derive a safe mod folder name.")
    return cleaned[:100]
