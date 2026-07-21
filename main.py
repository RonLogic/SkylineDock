from __future__ import annotations

import sys

from skylinedock.app import run


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else None)
