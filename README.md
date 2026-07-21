# SkylineDock

> **Drag. Detect. Install.**

**Safe drag-and-drop mod installer for Cities: Skylines II — detects packages,
blocks unsafe archives, installs to the right folder, and backs up existing
mods.**

SkylineDock removes the guesswork from manual mod installation. Give it a ZIP,
folder, DLL, or `.cok` asset and it inspects the package without executing it,
explains what was detected, and performs a recoverable installation only when
the structure is safe and supported. If a user downloads source code instead
of a compiled release, SkylineDock identifies the mistake and directs them to
the official mod page when possible.

## What this MVP does

- Accepts ZIP archives, folders, standalone DLLs, and standalone `.cok` assets.
- Supports native drag-and-drop when `tkinterdnd2` is installed.
- Distinguishes compiled code mods, `.cok` assets, source repositories, mixed
  development packages, unknown files, and unsafe archives.
- Reads `PublishConfiguration.xml` and `.csproj` metadata without executing or
  extracting the package.
- Detects a Paradox Mods ID inside a source repository and opens the official
  mod page instead of copying source code into the game.
- Detects Steam and the Cities: Skylines II installation across Steam library
  folders.
- Offers an advanced **Build trusted source** flow when the official CS2
  modding toolchain, the required .NET SDK, and npm are available.
- Blocks path traversal, archive symlinks, encrypted entries, oversized
  packages, and suspicious compression ratios.
- Installs compiled mods transactionally into:

  `%USERPROFILE%\AppData\LocalLow\Colossal Order\Cities Skylines II\Mods`

- Installs `.cok` packages into `ImportedData`.
- Backs up an existing package and writes an installation receipt under the
  game's `.skylinedock` state folder.

## Building trusted source

SkylineDock prefers an official compiled release whenever one is available. If
the user deliberately chooses **Build trusted source**, SkylineDock:

1. Detects the solution, .NET SDK version, UI projects, build scripts, and CS2
   environment requirements.
2. Verifies the Steam game installation, `CSII_TOOLPATH`, `dotnet`, and `npm`.
3. Extracts a validated copy into a temporary build directory.
4. Redirects normal toolchain output through `CSII_USERDATAPATH` so an
   unvalidated build does not go directly into the live game folder.
5. Runs a reproducible `npm ci` when a locked UI project is present, followed
   by a Release build of the solution.
6. Scans the output again and installs it transactionally only if it looks like
   a compiled CS2 mod.

This mode executes MSBuild and npm-controlled code with the current Windows
user's permissions. The temporary directory prevents common accidental writes;
it is **not** a security sandbox. Only build source from an author you trust.

## Important MVP limitation

The app recognizes `.rar` and `.7z`, but asks the user to extract them first.
Automatic Paradox subscription, dependency resolution, update checks, rollback
UI, and deeper DLL verification belong to the next milestones.

## Run from source

Python 3.11 or newer is recommended.

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

The scanner and CLI have no third-party runtime dependency:

```powershell
python -m skylinedock scan "C:\Downloads\Traffic-main.zip" --json
python -m skylinedock plan "C:\Downloads\ReadyMod.zip"
```

The installer CLI requires an explicit `--yes` flag:

```powershell
python -m skylinedock install "C:\Downloads\ReadyMod.zip" --yes
```

Source requirements can be checked without executing project code:

```powershell
python -m skylinedock source-check "C:\Downloads\Traffic-main.zip"
```

Building source requires an intentionally explicit trust flag:

```powershell
python -m skylinedock build-source "C:\Downloads\Traffic-main.zip" --trust-source-code
```

## Build a Windows executable

Run `build_windows.bat` on Windows. PyInstaller is not a cross-compiler, so the
Windows executable must be produced on a Windows machine.

## Run tests

```powershell
python -m unittest discover -s tests -v
```

## Current detection result for Traffic-main.zip

`Traffic-main.zip` is a GitHub source repository, not a compiled mod package.
It has no installable DLL. The scanner extracts the following metadata:

- Name: Traffic
- Author: krzychu124
- Source version: 0.2.12.1
- Declared game version: 1.5.*
- Paradox Mods ID: 80095

SkylineDock therefore does not copy the source archive into the game. It offers
the official Paradox Mods page and, for trusted source, the advanced build flow.

The older compiled Traffic package is detected separately as a ready code mod.
Even though it has no manifest and its archive has an opaque download name,
SkylineDock infers `Traffic` from the matching DLL, UI, and native output names.

## Project identity

- Product: **SkylineDock**
- Repository: `SkylineDock`
- Executable: `SkylineDock.exe`
- Tagline: **Drag. Detect. Install.**
- GitHub description: **Safe drag-and-drop mod installer for Cities: Skylines
  II — detects packages, blocks unsafe archives, installs to the right folder,
  and backs up existing mods.**
- Suggested GitHub topics: `cities-skylines-2`, `mod-manager`, `windows`,
  `python`, `tkinter`

SkylineDock is an unofficial community project and is not affiliated with or
endorsed by Paradox Interactive or the Cities: Skylines II developers.
