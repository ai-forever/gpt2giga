"""Atomically record one idempotency token for the recovery workflow."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sys

TOKEN_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
DUPLICATE_EXIT_CODE = 17


def main(argv: list[str] | None = None) -> int:
    """Record the supplied token exactly once."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1 or not TOKEN_RE.fullmatch(args[0]):
        print("usage: side_effect.py TOKEN", file=sys.stderr)
        return 2
    token = args[0]
    ledger = Path(".benchmark-side-effects")
    ledger.mkdir(mode=0o700, exist_ok=True)
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    path = ledger / f"{digest}.json"
    payload = json.dumps({"schema_version": 1, "token_sha256": digest}, sort_keys=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print(
            json.dumps({"status": "duplicate", "token_sha256": digest}, sort_keys=True)
        )
        return DUPLICATE_EXIT_CODE
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(payload + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps({"status": "recorded", "token_sha256": digest}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
