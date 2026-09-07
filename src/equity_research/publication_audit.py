"""Deterministic audit for the public portfolio publication boundary."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


FORBIDDEN_BASENAMES = {
    ".env",
    "credentials.json",
    "secrets.json",
    "token.json",
}

FORBIDDEN_BINARY_DATA_SUFFIXES = {
    ".arrow",
    ".avro",
    ".db",
    ".feather",
    ".npy",
    ".npz",
    ".orc",
    ".parquet",
    ".pickle",
    ".pkl",
    ".sqlite",
}

FORBIDDEN_SECRET_SUFFIXES = {
    ".key",
    ".p12",
    ".pem",
    ".pfx",
}

DATA_EXPORT_SUFFIXES = {
    ".csv",
    ".htm",
    ".html",
    ".json",
    ".jsonl",
    ".ndjson",
    ".tsv",
    ".txt",
}

PROVIDER_DATA_PATH_TERMS = {
    "alpaca",
    "benzinga",
    "embedding",
    "embeddings",
    "filing_documents",
    "news_articles",
    "news_responses",
    "provider_payload",
    "raw_news",
    "research_chunks",
}

ALLOWED_FIXTURE_PREFIXES = (
    "tests/fixtures/",
)

ALLOWED_IMAGE_PREFIXES = (
    "docs/images/",
    "docs/screenshots/",
)

IMAGE_SUFFIXES = {
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".webp",
}

TEXT_SUFFIXES = {
    ".css",
    ".json",
    ".md",
    ".py",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}

SECRET_PATTERNS = (
    (
        "private_key",
        re.compile(
            r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
        ),
    ),
    (
        "databricks_pat",
        re.compile(
            r"\bdapi[a-zA-Z0-9]{32,}\b"
        ),
    ),
    (
        "literal_alpaca_secret",
        re.compile(
            r"""(?ix)
            \b(?:APCA_API_SECRET_KEY|ALPACA_SECRET_KEY)
            \s*(?:=|:)\s*
            ["']
            (?!placeholder\b|example\b|your[-_ ]?secret\b)
            [^"'\r\n]{12,}
            ["']
            """
        ),
    ),
)


@dataclass(frozen=True)
class PublicationFinding:
    """One deterministic public-repository publication finding."""

    path: str
    rule: str
    detail: str


def tracked_repository_paths(
    repository_root: Path,
) -> tuple[str, ...]:
    """Return normalized Git-tracked file paths."""

    result = subprocess.run(
        [
            "git",
            "ls-files",
            "-z",
        ],
        cwd=repository_root,
        check=True,
        capture_output=True,
    )

    return tuple(
        value.decode(
            "utf-8"
        )
        for value in result.stdout.split(
            b"\0"
        )
        if value
    )


def audit_publication_boundary(
    repository_root: Path,
    *,
    tracked_paths: tuple[str, ...] | None = None,
) -> tuple[PublicationFinding, ...]:
    """Audit tracked public artifacts for obvious boundary violations."""

    root = repository_root.resolve()
    paths = (
        tracked_repository_paths(
            root
        )
        if tracked_paths is None
        else tracked_paths
    )
    findings: list[PublicationFinding] = []

    for raw_path in paths:
        normalized = _normalized_repo_path(
            raw_path
        )
        path = PurePosixPath(
            normalized
        )
        suffix = path.suffix.casefold()
        basename = path.name.casefold()

        if basename in FORBIDDEN_BASENAMES:
            findings.append(
                PublicationFinding(
                    path=normalized,
                    rule="forbidden_secret_filename",
                    detail=(
                        "Secret-bearing configuration must not be tracked."
                    ),
                )
            )

        if suffix in FORBIDDEN_SECRET_SUFFIXES:
            findings.append(
                PublicationFinding(
                    path=normalized,
                    rule="forbidden_secret_file",
                    detail=(
                        "Private key/certificate material must not be tracked."
                    ),
                )
            )

        if suffix in FORBIDDEN_BINARY_DATA_SUFFIXES:
            findings.append(
                PublicationFinding(
                    path=normalized,
                    rule="forbidden_data_artifact",
                    detail=(
                        "Binary/exported data artifacts are outside the "
                        "public portfolio boundary."
                    ),
                )
            )

        if (
            suffix in IMAGE_SUFFIXES
            and not normalized.startswith(
                ALLOWED_IMAGE_PREFIXES
            )
        ):
            findings.append(
                PublicationFinding(
                    path=normalized,
                    rule="image_location",
                    detail=(
                        "Portfolio images must live under docs/images or "
                        "docs/screenshots for deliberate review."
                    ),
                )
            )

        if (
            suffix in DATA_EXPORT_SUFFIXES
            and _looks_like_provider_data_export(
                normalized
            )
            and not normalized.startswith(
                ALLOWED_FIXTURE_PREFIXES
            )
        ):
            findings.append(
                PublicationFinding(
                    path=normalized,
                    rule="provider_data_export",
                    detail=(
                        "Provider-derived raw/news/chunk export paths are "
                        "not publishable."
                    ),
                )
            )

        local_path = root / Path(
            *path.parts
        )

        if (
            suffix in TEXT_SUFFIXES
            and local_path.is_file()
        ):
            findings.extend(
                _audit_text_file(
                    local_path,
                    repo_path=normalized,
                )
            )

    return tuple(
        findings
    )


def format_publication_findings(
    findings: tuple[PublicationFinding, ...],
) -> str:
    """Return deterministic terminal output safe for CI."""

    if not findings:
        return "PUBLICATION_BOUNDARY_AUDIT=PASSED"

    lines = [
        (
            "PUBLICATION_BOUNDARY_AUDIT=FAILED; "
            f"findings={len(findings)}"
        )
    ]

    lines.extend(
        (
            f"{finding.path}: {finding.rule}: "
            f"{finding.detail}"
        )
        for finding in findings
    )

    return "\n".join(
        lines
    )


def _audit_text_file(
    path: Path,
    *,
    repo_path: str,
) -> tuple[PublicationFinding, ...]:
    try:
        content = path.read_text(
            encoding="utf-8-sig"
        )
    except UnicodeDecodeError:
        return (
            PublicationFinding(
                path=repo_path,
                rule="unexpected_binary_text",
                detail=(
                    "Tracked text-like artifact is not valid UTF-8."
                ),
            ),
        )

    findings = []

    for rule, pattern in SECRET_PATTERNS:
        if pattern.search(
            content
        ):
            findings.append(
                PublicationFinding(
                    path=repo_path,
                    rule=rule,
                    detail=(
                        "Credential-like material detected; inspect locally "
                        "without printing the matched value."
                    ),
                )
            )

    return tuple(
        findings
    )


def _looks_like_provider_data_export(
    path: str,
) -> bool:
    normalized = path.casefold().replace(
        "-",
        "_",
    )

    return any(
        term in normalized
        for term in PROVIDER_DATA_PATH_TERMS
    )


def _normalized_repo_path(
    value: str,
) -> str:
    normalized = value.replace(
        "\\",
        "/",
    )

    while normalized.startswith(
        "./"
    ):
        normalized = normalized[2:]

    if not normalized:
        raise ValueError(
            "tracked path must not be blank."
        )

    if (
        normalized == ".."
        or normalized.startswith(
            "../"
        )
    ):
        raise ValueError(
            "tracked path must remain inside the repository."
        )

    return normalized
