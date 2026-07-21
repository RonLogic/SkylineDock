from __future__ import annotations

from datetime import datetime, timezone
import threading
import tempfile
import webbrowser
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, X, filedialog, messagebox
import tkinter as tk
from tkinter import ttk

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    DND_AVAILABLE = True
except ImportError:  # The app remains usable through the Browse button.
    DND_FILES = None
    TkinterDnD = None
    DND_AVAILABLE = False

from .installer import InstallError, build_install_plan, install
from .models import PackageKind, ScanReport
from .scanner import ArchiveScanner
from .settings import AppSettings, default_settings_path, load_settings, save_settings
from .source_builder import (
    SourceBuildError,
    build_trusted_source,
    check_source_build_prerequisites,
    inspect_source_build,
)
from .steam import detect_cs2_steam_installation, validate_cs2_game_path


COLORS = {
    "background": "#0B1020",
    "panel": "#121A2D",
    "panel_alt": "#18233A",
    "text": "#F5F7FC",
    "muted": "#9EABC2",
    "accent": "#6D8DFF",
    "accent_active": "#5576EC",
    "good": "#48D597",
    "warning": "#FFB84A",
    "danger": "#FF6B7A",
}

UNITY_LICENSE_URL = "https://docs.unity.com/en-us/hub/manage-license"
NODE_DOWNLOAD_URL = "https://nodejs.org/en/download"
DOTNET_DOWNLOAD_URL = "https://dotnet.microsoft.com/en-us/download/dotnet"
DOTNET_RUNTIME_DOWNLOAD_URL = "https://dotnet.microsoft.com/en-us/download/dotnet/{family}"


class SkylineDockApp:
    def __init__(self, initial_path: str | None = None) -> None:
        self.root = TkinterDnD.Tk() if DND_AVAILABLE else tk.Tk()
        self.root.title("SkylineDock")
        self.root.geometry("980x740")
        self.root.minsize(860, 660)
        self.root.configure(bg=COLORS["background"])

        self.scanner = ArchiveScanner()
        self.report: ScanReport | None = None
        self.settings: AppSettings = load_settings()
        self.game_path: Path | None = None
        self.game_path_source: str | None = None
        self._build_styles()
        self._build_ui()
        self._load_game_location()

        if initial_path:
            self.root.after(150, lambda: self.scan(Path(initial_path)))

    def run(self) -> None:
        self.root.mainloop()

    def _build_styles(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(
            "Primary.TButton",
            background=COLORS["accent"],
            foreground="white",
            borderwidth=0,
            focusthickness=0,
            padding=(20, 11),
            font=("Segoe UI Semibold", 10),
        )
        style.map(
            "Primary.TButton",
            background=[("active", COLORS["accent_active"]), ("disabled", "#36415B")],
            foreground=[("disabled", "#8A94A8")],
        )
        style.configure(
            "Secondary.TButton",
            background=COLORS["panel_alt"],
            foreground=COLORS["text"],
            borderwidth=0,
            padding=(18, 11),
            font=("Segoe UI Semibold", 10),
        )
        style.map("Secondary.TButton", background=[("active", "#22304C")])

    def _build_ui(self) -> None:
        header = tk.Frame(self.root, bg=COLORS["background"])
        header.pack(fill=X, padx=36, pady=(28, 18))
        tk.Label(
            header,
            text="SkylineDock",
            bg=COLORS["background"],
            fg=COLORS["text"],
            font=("Segoe UI Semibold", 24),
        ).pack(side=LEFT)
        tk.Label(
            header,
            text="Safe, one-step Cities: Skylines II mod setup",
            bg=COLORS["background"],
            fg=COLORS["muted"],
            font=("Segoe UI", 10),
        ).pack(side=LEFT, padx=(18, 0), pady=(9, 0))

        game_row = tk.Frame(self.root, bg=COLORS["panel_alt"], padx=16, pady=12)
        game_row.pack(fill=X, padx=36, pady=(0, 16))
        game_copy = tk.Frame(game_row, bg=COLORS["panel_alt"])
        game_copy.pack(side=LEFT, fill=X, expand=True)
        tk.Label(
            game_copy,
            text="GAME INSTALLATION",
            bg=COLORS["panel_alt"],
            fg=COLORS["muted"],
            font=("Segoe UI Semibold", 8),
        ).pack(anchor="w")
        self.game_path_label = tk.Label(
            game_copy,
            text="Detecting Cities: Skylines II…",
            bg=COLORS["panel_alt"],
            fg=COLORS["text"],
            font=("Segoe UI", 9),
            anchor="w",
            width=64,
        )
        self.game_path_label.pack(fill=X, pady=(2, 0))
        tk.Label(
            game_copy,
            text="Locates the game and build tools; mods still install into the CS2 AppData folder.",
            bg=COLORS["panel_alt"],
            fg=COLORS["muted"],
            font=("Segoe UI", 8),
            anchor="w",
        ).pack(fill=X, pady=(2, 0))
        ttk.Button(
            game_row,
            text="Auto-detect",
            style="Secondary.TButton",
            command=self._auto_detect_game_folder,
        ).pack(side=RIGHT, padx=(8, 0))
        ttk.Button(
            game_row,
            text="Choose game folder",
            style="Secondary.TButton",
            command=self._choose_game_folder,
        ).pack(side=RIGHT, padx=(12, 0))

        self.drop_frame = tk.Frame(
            self.root,
            bg=COLORS["panel"],
            highlightbackground="#2B3856",
            highlightthickness=2,
            cursor="hand2",
        )
        self.drop_frame.pack(fill=X, padx=36, pady=(0, 18), ipady=24)
        self.drop_frame.bind("<Button-1>", lambda _event: self._browse())

        self.drop_title = tk.Label(
            self.drop_frame,
            text="Drop a ZIP or mod folder here",
            bg=COLORS["panel"],
            fg=COLORS["text"],
            font=("Segoe UI Semibold", 15),
        )
        self.drop_title.pack(pady=(12, 5))
        self.drop_title.bind("<Button-1>", lambda _event: self._browse())
        tk.Label(
            self.drop_frame,
            text="or click to browse  •  ZIP and folders supported in this MVP",
            bg=COLORS["panel"],
            fg=COLORS["muted"],
            font=("Segoe UI", 10),
        ).pack()

        if DND_AVAILABLE:
            self.drop_frame.drop_target_register(DND_FILES)
            self.drop_frame.dnd_bind("<<Drop>>", self._on_drop)

        result_panel = tk.Frame(self.root, bg=COLORS["panel"], padx=24, pady=20)
        result_panel.pack(fill=BOTH, expand=True, padx=36, pady=(0, 22))

        top_row = tk.Frame(result_panel, bg=COLORS["panel"])
        top_row.pack(fill=X)
        self.status_badge = tk.Label(
            top_row,
            text="WAITING FOR A PACKAGE",
            bg=COLORS["panel_alt"],
            fg=COLORS["muted"],
            padx=12,
            pady=6,
            font=("Segoe UI Semibold", 9),
        )
        self.status_badge.pack(side=LEFT)
        self.package_name = tk.Label(
            top_row,
            text="",
            bg=COLORS["panel"],
            fg=COLORS["text"],
            font=("Segoe UI Semibold", 17),
        )
        self.package_name.pack(side=LEFT, padx=(16, 0))

        self.details = tk.Text(
            result_panel,
            height=12,
            bg=COLORS["panel"],
            fg=COLORS["muted"],
            insertbackground=COLORS["text"],
            selectbackground=COLORS["accent"],
            relief="flat",
            borderwidth=0,
            font=("Cascadia Mono", 10),
            wrap="word",
            padx=0,
            pady=14,
        )
        self.details.pack(fill=BOTH, expand=True)
        self.details.insert(END, "Drop a package to inspect it without changing your game files.")
        self.details.configure(state="disabled")

        actions = tk.Frame(result_panel, bg=COLORS["panel"])
        actions.pack(fill=X, pady=(8, 0))
        self.open_button = ttk.Button(
            actions,
            text="Open official mod",
            style="Secondary.TButton",
            command=self._open_official,
            state="disabled",
        )
        self.open_button.pack(side=RIGHT, padx=(10, 0))
        self.build_button = ttk.Button(
            actions,
            text="Build trusted source",
            style="Secondary.TButton",
            command=self._build_source,
            state="disabled",
        )
        self.build_button.pack(side=RIGHT, padx=(10, 0))
        self.install_button = ttk.Button(
            actions,
            text="Install safely",
            style="Primary.TButton",
            command=self._install,
            state="disabled",
        )
        self.install_button.pack(side=RIGHT)

        self.footer = tk.Label(
            self.root,
            text="Nothing is extracted or executed during scanning.",
            bg=COLORS["background"],
            fg=COLORS["muted"],
            font=("Segoe UI", 9),
        )
        self.footer.pack(pady=(0, 16))

    def _browse(self) -> None:
        selected = filedialog.askopenfilename(
            title="Select a CS2 mod package",
            filetypes=[("ZIP archives", "*.zip"), ("All files", "*.*")],
        )
        if selected:
            self.scan(Path(selected))

    def _load_game_location(self) -> None:
        if self.settings.game_path:
            validated = validate_cs2_game_path(self.settings.game_path)
            if validated:
                self._set_game_location(validated, "manual")
                return

        detected = detect_cs2_steam_installation()
        if detected:
            self._set_game_location(detected.game_path, "Steam auto-detected")
        else:
            self._set_game_location(None, None)

    def _choose_game_folder(self) -> None:
        initial = str(self.game_path) if self.game_path else None
        selected = filedialog.askdirectory(
            title="Select the Cities: Skylines II installation folder",
            initialdir=initial,
            mustexist=True,
        )
        if not selected:
            return

        validated = validate_cs2_game_path(selected)
        if validated is None:
            messagebox.showerror(
                "Invalid game folder",
                "Choose the folder that contains Cities2.exe.\n\n"
                "Example:\nC:\\Program Files (x86)\\Steam\\steamapps\\common\\Cities Skylines II",
            )
            return

        self.settings.game_path = str(validated)
        self._save_settings()
        self._set_game_location(validated, "manual")

    def _auto_detect_game_folder(self) -> None:
        detected = detect_cs2_steam_installation()
        if detected is None:
            messagebox.showerror(
                "Game not detected",
                "Cities: Skylines II was not found in the configured Steam libraries. "
                "Use Choose game folder instead.",
            )
            return

        self.settings.game_path = None
        self._save_settings()
        self._set_game_location(detected.game_path, "Steam auto-detected")

    def _save_settings(self) -> None:
        try:
            save_settings(self.settings)
        except OSError as exc:
            messagebox.showwarning(
                "Settings were not saved",
                f"The folder will work for this session, but could not be saved:\n{exc}",
            )

    def _set_game_location(self, path: Path | None, source: str | None) -> None:
        self.game_path = path
        self.game_path_source = source
        if path is None:
            self.game_path_label.configure(
                text="Game not detected — choose the installation folder manually.",
                fg=COLORS["warning"],
            )
            return
        self.game_path_label.configure(text=f"{path}  •  {source}", fg=COLORS["text"])

    def _on_drop(self, event: object) -> None:
        paths = self.root.tk.splitlist(event.data)
        if paths:
            self.scan(Path(paths[0]))

    def scan(self, path: Path) -> None:
        self._set_loading(path)

        def worker() -> None:
            report = self.scanner.scan(path)
            self.root.after(0, lambda: self._show_report(report))

        threading.Thread(target=worker, daemon=True).start()

    def _set_loading(self, path: Path) -> None:
        self.report = None
        self.status_badge.configure(text="SCANNING", bg="#243457", fg="#BFD0FF")
        self.package_name.configure(text=path.name)
        self._set_details("Inspecting structure and metadata…")
        self.install_button.configure(state="disabled")
        self.open_button.configure(state="disabled")
        self.build_button.configure(state="disabled")

    def _show_report(self, report: ScanReport) -> None:
        self.report = report
        badge, color = self._badge_for(report.kind)
        self.status_badge.configure(text=badge, bg=color, fg="#07111A")
        self.package_name.configure(text=report.display_name)

        lines = [
            f"Type:          {report.kind.value.replace('_', ' ')}",
            f"Source:        {report.source_type.value}",
            f"Files:         {report.file_count:,}",
            f"Expanded size: {self._format_bytes(report.uncompressed_size)}",
        ]
        if report.metadata.version:
            lines.append(f"Mod version:   {report.metadata.version}")
        if report.metadata.game_version:
            lines.append(f"Game version:  {report.metadata.game_version}")
        if report.metadata.author:
            lines.append(f"Author:        {report.metadata.author}")
        if report.metadata.paradox_mod_id:
            lines.append(f"Paradox ID:    {report.metadata.paradox_mod_id}")
        lines.extend(["", report.recommended_action])

        if report.warnings:
            lines.extend(["", "Warnings:", *[f"  • {item}" for item in report.warnings]])
        if report.errors:
            lines.extend(["", "Blocked:", *[f"  • {item}" for item in report.errors]])

        self._set_details("\n".join(lines))
        self.install_button.configure(state="normal" if report.can_install else "disabled")
        self.open_button.configure(
            state="normal" if report.metadata.paradox_url else "disabled"
        )
        self.build_button.configure(
            state="normal" if report.kind == PackageKind.SOURCE_REPOSITORY else "disabled"
        )

    def _install(self) -> None:
        if not self.report:
            return
        try:
            plan = build_install_plan(self.report)
            approved = messagebox.askyesno(
                "Confirm installation",
                f"Install {self.report.display_name} to:\n\n{plan.destination}\n\n"
                "An existing copy will be backed up first.",
            )
            if not approved:
                return
            destination = install(plan)
            messagebox.showinfo("Installed", f"Installed successfully to:\n{destination}")
            self.footer.configure(text=f"Installed: {destination}", fg=COLORS["good"])
        except InstallError as exc:
            messagebox.showerror("Installation blocked", str(exc))

    def _open_official(self) -> None:
        if self.report and self.report.metadata.paradox_url:
            webbrowser.open(self.report.metadata.paradox_url)

    def _build_source(self) -> None:
        if not self.report or self.report.kind != PackageKind.SOURCE_REPOSITORY:
            return

        try:
            inspection = inspect_source_build(self.report)
            prerequisites = check_source_build_prerequisites(
                inspection,
                game_path=self.game_path,
            )
        except SourceBuildError as exc:
            messagebox.showerror("Source build unavailable", str(exc))
            return

        if not prerequisites.ready:
            self._show_build_requirements(inspection, prerequisites)
            return

        warnings = "\n".join(f"• {warning}" for warning in inspection.warnings)
        approved = messagebox.askyesno(
            "Build trusted source?",
            "Building source runs commands supplied by the mod author. Continue only if you "
            "trust the source and have closed Cities: Skylines II.\n\n"
            f"{warnings}\n\n"
            "SkylineDock will build a temporary copy, validate the output, and back up an "
            "existing installation before replacing it.",
        )
        if not approved:
            return

        report = self.report
        self.status_badge.configure(text="BUILDING SOURCE", bg="#243457", fg="#BFD0FF")
        self.install_button.configure(state="disabled")
        self.build_button.configure(state="disabled")
        self.open_button.configure(state="disabled")
        self.footer.configure(text="Building in a temporary workspace…", fg=COLORS["muted"])

        def worker() -> None:
            try:
                with tempfile.TemporaryDirectory(prefix="SkylineDock-build-") as temporary:
                    result = build_trusted_source(
                        report,
                        temporary,
                        trusted_source_confirmed=True,
                        prerequisites=prerequisites,
                    )
                    plan = build_install_plan(result.compiled_report)
                    destination = install(plan)
                self.root.after(0, lambda: self._source_build_succeeded(destination))
            except SourceBuildError as exc:
                message = str(exc)
                log_path = self._save_source_build_log(exc.diagnostic_log)
                if log_path is not None:
                    message += f"\n\nFull diagnostic log:\n{log_path}"
                self.root.after(0, lambda message=message: self._source_build_failed(message))
            except (InstallError, OSError) as exc:
                message = str(exc)
                self.root.after(0, lambda message=message: self._source_build_failed(message))

        threading.Thread(target=worker, daemon=True).start()

    def _show_build_requirements(self, inspection, prerequisites) -> None:
        """Explain missing build tools without exposing environment-variable setup."""

        dialog = tk.Toplevel(self.root)
        dialog.withdraw()
        dialog.title("One-time setup required")
        dialog.configure(bg=COLORS["background"])
        dialog.resizable(False, False)
        dialog.transient(self.root)

        content = tk.Frame(dialog, bg=COLORS["background"], padx=28, pady=24)
        content.pack(fill=BOTH, expand=True)
        tk.Label(
            content,
            text="A one-time setup is needed to build this source mod",
            bg=COLORS["background"],
            fg=COLORS["text"],
            font=("Segoe UI Semibold", 15),
        ).pack(anchor="w")
        tk.Label(
            content,
            text=(
                "These free components are only needed when building source code. "
                "Ready-to-install mods do not need them."
            ),
            bg=COLORS["background"],
            fg=COLORS["muted"],
            font=("Segoe UI", 9),
            justify=LEFT,
            wraplength=610,
        ).pack(anchor="w", pady=(5, 18))

        missing_toolchain = prerequisites.tool_path is None
        missing_npm = bool(inspection.ui_directories) and prerequisites.npm_executable is None
        missing_dotnet = prerequisites.dotnet_executable is None
        missing_runtimes = prerequisites.missing_dotnet_runtimes
        requirement_number = 1

        if missing_toolchain:
            self._add_requirement(
                content,
                f"{requirement_number}. Install the Cities: Skylines II Modding Toolchain",
                "Open the game, go to Options → Modding, then install or repair all "
                "required tools. If installation waits for a Unity license, open Unity Hub, "
                "sign in, then choose Licenses → Add license → Get a free personal license. "
                "Return to the game and wait for every item to show a green check.",
                "Unity license guide",
                UNITY_LICENSE_URL,
            )
            requirement_number += 1

        if missing_npm:
            self._add_requirement(
                content,
                f"{requirement_number}. Install Node.js LTS",
                "Download the Windows installer and keep the default options. npm is included "
                "with Node.js; it does not need to be installed separately.",
                "Download Node.js",
                NODE_DOWNLOAD_URL,
            )
            requirement_number += 1

        if missing_dotnet:
            version = inspection.dotnet_sdk_version or "a compatible current version"
            self._add_requirement(
                content,
                f"{requirement_number}. Install the .NET SDK",
                f"Install .NET SDK {version} or a compatible newer SDK for Windows.",
                "Download .NET SDK",
                DOTNET_DOWNLOAD_URL,
            )
            requirement_number += 1

        for runtime in missing_runtimes:
            self._add_requirement(
                content,
                f"{requirement_number}. Install .NET Runtime {runtime.family} (x64)",
                "The CS2 ModPostProcessor targets "
                f"{runtime.framework} {runtime.version}. A newer major runtime does not "
                "replace this requirement automatically. Install the latest patch in the "
                f"{runtime.family} family; other installed .NET versions can remain.",
                f"Download .NET {runtime.family} Runtime",
                DOTNET_RUNTIME_DOWNLOAD_URL.format(family=runtime.family),
            )
            requirement_number += 1

        other_issues = []
        if not prerequisites.windows_supported:
            other_issues.append("Source builds are currently supported on Windows only.")
        if prerequisites.steam_game_path is None:
            other_issues.append(
                "Choose the folder containing Cities2.exe in SkylineDock before building."
            )
        if other_issues:
            tk.Label(
                content,
                text="\n".join(f"• {issue}" for issue in other_issues),
                bg=COLORS["background"],
                fg=COLORS["warning"],
                font=("Segoe UI", 9),
                justify=LEFT,
                wraplength=610,
            ).pack(anchor="w", pady=(0, 14))

        tk.Label(
            content,
            text=(
                "When installation is complete, restart SkylineDock, load the package again, "
                "and click Build trusted source. SkylineDock will detect the tools automatically."
            ),
            bg=COLORS["panel_alt"],
            fg=COLORS["text"],
            font=("Segoe UI Semibold", 9),
            justify=LEFT,
            wraplength=590,
            padx=14,
            pady=12,
        ).pack(fill=X, pady=(2, 18))
        ttk.Button(
            content,
            text="Close",
            style="Primary.TButton",
            command=dialog.destroy,
        ).pack(anchor="e")

        dialog.update_idletasks()
        x = self.root.winfo_rootx() + max(
            0, (self.root.winfo_width() - dialog.winfo_width()) // 2
        )
        y = self.root.winfo_rooty() + max(
            0, (self.root.winfo_height() - dialog.winfo_height()) // 2
        )
        dialog.geometry(f"+{x}+{y}")
        dialog.deiconify()
        dialog.grab_set()

    @staticmethod
    def _add_requirement(
        parent: tk.Widget,
        title: str,
        explanation: str,
        button_text: str,
        url: str,
    ) -> None:
        panel = tk.Frame(parent, bg=COLORS["panel_alt"], padx=14, pady=12)
        panel.pack(fill=X, pady=(0, 10))
        copy = tk.Frame(panel, bg=COLORS["panel_alt"])
        copy.pack(side=LEFT, fill=X, expand=True)
        tk.Label(
            copy,
            text=title,
            bg=COLORS["panel_alt"],
            fg=COLORS["text"],
            font=("Segoe UI Semibold", 10),
        ).pack(anchor="w")
        tk.Label(
            copy,
            text=explanation,
            bg=COLORS["panel_alt"],
            fg=COLORS["muted"],
            font=("Segoe UI", 9),
            justify=LEFT,
            wraplength=430,
        ).pack(anchor="w", pady=(3, 0))
        ttk.Button(
            panel,
            text=button_text,
            style="Secondary.TButton",
            command=lambda: webbrowser.open(url),
        ).pack(side=RIGHT, padx=(16, 0))

    def _source_build_succeeded(self, destination: Path) -> None:
        self.status_badge.configure(text="BUILT & INSTALLED", bg=COLORS["good"], fg="#07111A")
        self.footer.configure(text=f"Installed: {destination}", fg=COLORS["good"])
        self.build_button.configure(state="normal")
        if self.report and self.report.metadata.paradox_url:
            self.open_button.configure(state="normal")
        messagebox.showinfo(
            "Source build complete",
            f"The source was built, validated, and installed to:\n{destination}",
        )

    def _source_build_failed(self, message: str) -> None:
        self.status_badge.configure(text="BUILD FAILED", bg=COLORS["danger"], fg="#07111A")
        self.footer.configure(text="No unvalidated build was installed.", fg=COLORS["danger"])
        self.build_button.configure(state="normal")
        if self.report and self.report.metadata.paradox_url:
            self.open_button.configure(state="normal")
        messagebox.showerror("Source build failed", message)

    @staticmethod
    def _save_source_build_log(log_text: str | None) -> Path | None:
        if not log_text:
            return None

        try:
            log_directory = default_settings_path().parent / "logs"
            log_directory.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S-%fZ")
            log_path = log_directory / f"source-build-{timestamp}.log"
            log_path.write_text(log_text, encoding="utf-8")
        except OSError:
            return None
        return log_path

    def _set_details(self, value: str) -> None:
        self.details.configure(state="normal")
        self.details.delete("1.0", END)
        self.details.insert(END, value)
        self.details.configure(state="disabled")

    @staticmethod
    def _badge_for(kind: PackageKind) -> tuple[str, str]:
        if kind in {PackageKind.READY_CODE_MOD, PackageKind.ASSET_PACKAGE}:
            return "READY TO INSTALL", COLORS["good"]
        if kind == PackageKind.SOURCE_REPOSITORY:
            return "SOURCE CODE DETECTED", COLORS["warning"]
        if kind == PackageKind.MIXED_SOURCE_PACKAGE:
            return "REVIEW REQUIRED", COLORS["warning"]
        if kind == PackageKind.INVALID:
            return "BLOCKED", COLORS["danger"]
        return "NOT RECOGNIZED", COLORS["warning"]

    @staticmethod
    def _format_bytes(size: int) -> str:
        value = float(size)
        for unit in ("B", "KiB", "MiB", "GiB"):
            if value < 1024 or unit == "GiB":
                return f"{value:.1f} {unit}"
            value /= 1024
        return f"{value:.1f} GiB"


def run(initial_path: str | None = None) -> None:
    SkylineDockApp(initial_path).run()
