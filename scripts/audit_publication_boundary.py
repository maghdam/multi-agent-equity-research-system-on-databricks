"""Audit Git-tracked portfolio artifacts against the publication boundary."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(SRC_ROOT),
    )

from equity_research.publication_audit import (  # noqa: E402
    audit_publication_boundary,
    format_publication_findings,
)


def main() -> int:
    findings = audit_publication_boundary(
        PROJECT_ROOT
    )
    print(
        format_publication_findings(
            findings
        )
    )

    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
