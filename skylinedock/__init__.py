"""SkylineDock package scanner and transactional CS2 mod installer."""

from .models import PackageKind, ScanReport, SourceType
from .scanner import ArchiveScanner

__all__ = ["ArchiveScanner", "PackageKind", "ScanReport", "SourceType"]

__version__ = "0.2.0.dev1"
