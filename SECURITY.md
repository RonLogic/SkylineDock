# Security policy

## Supported versions

SkylineDock is currently pre-release software. Only the newest commit and the
newest published release receive security fixes.

## Reporting a vulnerability

Please use GitHub's **Private vulnerability reporting** feature instead of a
public issue. Include a minimal test archive when possible, but never include
personal game data or copyrighted mod packages without permission.

## Trust boundary

SkylineDock inspects archives without executing their contents and blocks
known unsafe path patterns. A compiled mod DLL is still executable code loaded
by the game. Users should install mods only from authors and sources they trust.

Source-build mode is an explicitly higher-risk operation: MSBuild targets,
NuGet tooling, webpack configuration, and npm scripts are executable code.
SkylineDock requires an additional confirmation and redirects normal build
output into a temporary workspace, but this is not a security sandbox. A
malicious build script could still access files and network resources available
to the current Windows account.
