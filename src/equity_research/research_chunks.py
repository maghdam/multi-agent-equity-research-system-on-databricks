"""Pure-Python deterministic chunking for RAG research documents."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from equity_research.research_documents import ResearchDocument


CHUNKING_ALGORITHM_VERSION = "structure-aware-char-v1"
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")

PARAGRAPH_BOUNDARY_PATTERN = re.compile(r"\n[ \t]*\n+")
SENTENCE_BOUNDARY_PATTERN = re.compile(
    r"""[.!?](?:["')\]]*)[ \t\n]+"""
)
WHITESPACE_BOUNDARY_PATTERN = re.compile(r"\s+")


@dataclass(frozen=True)
class ChunkingStrategy:
    """Versioned deterministic chunking parameters."""

    target_chars: int
    max_chars: int
    overlap_chars: int = 0
    algorithm_version: str = CHUNKING_ALGORITHM_VERSION

    def __post_init__(self) -> None:
        if (
            isinstance(self.target_chars, bool)
            or not isinstance(self.target_chars, int)
            or self.target_chars < 1
        ):
            raise ValueError("target_chars must be a positive integer.")

        if (
            isinstance(self.max_chars, bool)
            or not isinstance(self.max_chars, int)
            or self.max_chars < self.target_chars
        ):
            raise ValueError(
                "max_chars must be an integer greater than or equal to "
                "target_chars."
            )

        if (
            isinstance(self.overlap_chars, bool)
            or not isinstance(self.overlap_chars, int)
            or self.overlap_chars < 0
            or self.overlap_chars >= self.target_chars
        ):
            raise ValueError(
                "overlap_chars must be a nonnegative integer smaller than "
                "target_chars."
            )

        if (
            not isinstance(self.algorithm_version, str)
            or not self.algorithm_version.strip()
            or self.algorithm_version != self.algorithm_version.strip()
        ):
            raise ValueError(
                "algorithm_version must be a nonblank trimmed string."
            )

    @property
    def chunking_strategy_version(self) -> str:
        """Readable version containing every boundary-affecting parameter."""

        return (
            f"{self.algorithm_version}"
            f":target={self.target_chars}"
            f":max={self.max_chars}"
            f":overlap={self.overlap_chars}"
        )


@dataclass(frozen=True)
class ResearchChunk:
    """One deterministic retrieval unit from one research-document version."""

    chunk_id: str
    document_id: str
    document_version_id: str
    chunking_strategy_version: str
    source_type: str
    source_system: str
    configured_symbols: tuple[str, ...]
    title: str
    evidence_date: date
    source_url: str
    section_code: str | None
    section_title: str | None
    chunk_index: int
    character_start: int
    character_end: int
    chunk_text: str
    chunk_text_sha256: str
    source_response_id: str
    source_fetched_at: datetime
    source_ingestion_run_id: str


@dataclass(frozen=True)
class ResearchChunksSnapshotResult:
    """Complete deterministic current research-chunk snapshot."""

    chunks: tuple[ResearchChunk, ...]
    document_count: int

    @property
    def chunk_count(self) -> int:
        return len(self.chunks)


def build_research_chunks_snapshot(
    *,
    documents: Sequence[ResearchDocument],
    strategy: ChunkingStrategy,
) -> ResearchChunksSnapshotResult:
    """Chunk the complete current research-document snapshot."""

    if not isinstance(strategy, ChunkingStrategy):
        raise ValueError("strategy must be a ChunkingStrategy.")

    ordered_documents = tuple(
        sorted(
            documents,
            key=lambda document: (
                document.source_type,
                document.document_id,
            ),
        )
    )
    _validate_input_documents(ordered_documents)

    chunks: list[ResearchChunk] = []

    for document in ordered_documents:
        chunks.extend(
            build_research_chunks(
                document,
                strategy=strategy,
            )
        )

    result = tuple(chunks)
    _validate_chunk_snapshot(
        documents=ordered_documents,
        chunks=result,
        strategy=strategy,
    )

    return ResearchChunksSnapshotResult(
        chunks=result,
        document_count=len(ordered_documents),
    )


def build_research_chunks(
    document: ResearchDocument,
    *,
    strategy: ChunkingStrategy,
) -> tuple[ResearchChunk, ...]:
    """Build deterministic chunks for one exact research-document version."""

    if not isinstance(document, ResearchDocument):
        raise ValueError("document must be a ResearchDocument.")

    if not isinstance(strategy, ChunkingStrategy):
        raise ValueError("strategy must be a ChunkingStrategy.")

    _validate_document(document)

    spans = _chunk_spans(
        document.document_text,
        strategy=strategy,
    )

    chunks: list[ResearchChunk] = []

    for chunk_index, (start, end) in enumerate(spans):
        chunk_text = document.document_text[start:end]

        if not chunk_text or not chunk_text.strip():
            raise ValueError(
                f"{document.document_id}: chunk {chunk_index} is blank."
            )

        chunk_text_sha256 = _sha256_text(chunk_text)
        chunk_id = _sha256_canonical(
            {
                "character_end": end,
                "character_start": start,
                "chunk_index": chunk_index,
                "chunk_text_sha256": chunk_text_sha256,
                "chunking_strategy_version": (
                    strategy.chunking_strategy_version
                ),
                "document_version_id": document.document_version_id,
            }
        )

        chunks.append(
            ResearchChunk(
                chunk_id=chunk_id,
                document_id=document.document_id,
                document_version_id=document.document_version_id,
                chunking_strategy_version=(
                    strategy.chunking_strategy_version
                ),
                source_type=document.source_type,
                source_system=document.source_system,
                configured_symbols=document.configured_symbols,
                title=document.title,
                evidence_date=document.evidence_date,
                source_url=document.source_url,
                section_code=document.section_code,
                section_title=document.section_title,
                chunk_index=chunk_index,
                character_start=start,
                character_end=end,
                chunk_text=chunk_text,
                chunk_text_sha256=chunk_text_sha256,
                source_response_id=document.source_response_id,
                source_fetched_at=document.source_fetched_at,
                source_ingestion_run_id=(
                    document.source_ingestion_run_id
                ),
            )
        )

    return tuple(chunks)


def _chunk_spans(
    text: str,
    *,
    strategy: ChunkingStrategy,
) -> tuple[tuple[int, int], ...]:
    if not isinstance(text, str) or not text or not text.strip():
        raise ValueError("document_text must be a nonblank string.")

    spans: list[tuple[int, int]] = []
    start = 0
    text_length = len(text)

    while start < text_length:
        remaining = text_length - start

        if remaining <= strategy.max_chars:
            end = text_length
        else:
            end = _select_chunk_end(
                text,
                start=start,
                strategy=strategy,
            )

        if end <= start:
            raise ValueError("chunking failed to make forward progress.")

        spans.append((start, end))

        if end == text_length:
            break

        next_start = _select_next_start(
            text,
            previous_start=start,
            previous_end=end,
            overlap_chars=strategy.overlap_chars,
        )

        if next_start <= start or next_start >= end:
            if strategy.overlap_chars == 0:
                next_start = end
            else:
                next_start = max(
                    start + 1,
                    end - strategy.overlap_chars,
                )

        start = next_start

    return tuple(spans)


def _select_chunk_end(
    text: str,
    *,
    start: int,
    strategy: ChunkingStrategy,
) -> int:
    target = min(start + strategy.target_chars, len(text))
    limit = min(start + strategy.max_chars, len(text))

    for pattern in (
        PARAGRAPH_BOUNDARY_PATTERN,
        SENTENCE_BOUNDARY_PATTERN,
    ):
        boundary = _first_boundary_at_or_after(
            text,
            pattern=pattern,
            start=target,
            limit=limit,
        )
        if boundary is not None:
            return boundary

    for pattern in (
        PARAGRAPH_BOUNDARY_PATTERN,
        SENTENCE_BOUNDARY_PATTERN,
    ):
        boundary = _last_boundary_before(
            text,
            pattern=pattern,
            start=start,
            target=target,
        )
        if boundary is not None:
            return boundary

    whitespace = _last_boundary_before(
        text,
        pattern=WHITESPACE_BOUNDARY_PATTERN,
        start=start,
        target=limit,
    )
    if whitespace is not None:
        return whitespace

    return limit


def _first_boundary_at_or_after(
    text: str,
    *,
    pattern: re.Pattern[str],
    start: int,
    limit: int,
) -> int | None:
    for match in pattern.finditer(text, start, limit + 1):
        boundary = match.end()
        if start <= boundary <= limit:
            return boundary
    return None


def _last_boundary_before(
    text: str,
    *,
    pattern: re.Pattern[str],
    start: int,
    target: int,
) -> int | None:
    boundary: int | None = None

    for match in pattern.finditer(text, start, target + 1):
        candidate = match.end()
        if start < candidate <= target:
            boundary = candidate

    return boundary


def _select_next_start(
    text: str,
    *,
    previous_start: int,
    previous_end: int,
    overlap_chars: int,
) -> int:
    if overlap_chars == 0:
        return previous_end

    desired_start = max(
        previous_start + 1,
        previous_end - overlap_chars,
    )

    # Prefer starting after a preserved paragraph/sentence boundary while
    # keeping the actual overlap no larger than the configured bound.
    for pattern in (
        PARAGRAPH_BOUNDARY_PATTERN,
        SENTENCE_BOUNDARY_PATTERN,
        WHITESPACE_BOUNDARY_PATTERN,
    ):
        for match in pattern.finditer(
            text,
            desired_start,
            previous_end,
        ):
            candidate = match.end()
            if desired_start <= candidate < previous_end:
                return candidate

    return desired_start


def _validate_input_documents(
    documents: Sequence[ResearchDocument],
) -> None:
    document_ids: set[str] = set()
    version_ids: set[str] = set()

    for document in documents:
        _validate_document(document)

        if document.document_id in document_ids:
            raise ValueError(
                "research_documents document_id values must be unique."
            )
        document_ids.add(document.document_id)

        if document.document_version_id in version_ids:
            raise ValueError(
                "research_documents document_version_id values must be unique."
            )
        version_ids.add(document.document_version_id)


def _validate_document(document: ResearchDocument) -> None:
    if not isinstance(document, ResearchDocument):
        raise ValueError("documents must contain ResearchDocument values.")

    _required_string(document.document_id, "document_id")
    _validate_sha256(
        document.document_version_id,
        "document_version_id",
    )

    if not isinstance(document.document_text, str) or not document.document_text:
        raise ValueError(
            f"{document.document_id}: document_text must be nonblank."
        )

    if not document.document_text.strip():
        raise ValueError(
            f"{document.document_id}: document_text must be nonblank."
        )

    _validate_sha256(
        document.document_text_sha256,
        "document_text_sha256",
    )

    if _sha256_text(document.document_text) != document.document_text_sha256:
        raise ValueError(
            f"{document.document_id}: document_text_sha256 mismatch."
        )


def _validate_chunk_snapshot(
    *,
    documents: Sequence[ResearchDocument],
    chunks: Sequence[ResearchChunk],
    strategy: ChunkingStrategy,
) -> None:
    expected_versions = {
        document.document_version_id: document
        for document in documents
    }
    grouped: dict[str, list[ResearchChunk]] = {
        version_id: []
        for version_id in expected_versions
    }

    chunk_ids: set[str] = set()

    for chunk in chunks:
        if chunk.chunk_id in chunk_ids:
            raise ValueError("research_chunks chunk_id values must be unique.")
        chunk_ids.add(chunk.chunk_id)

        parent = expected_versions.get(chunk.document_version_id)
        if parent is None:
            raise ValueError(
                f"{chunk.chunk_id}: parent document version is not current."
            )

        if (
            chunk.chunking_strategy_version
            != strategy.chunking_strategy_version
        ):
            raise ValueError(
                f"{chunk.chunk_id}: chunking strategy version mismatch."
            )

        if not (
            0 <= chunk.character_start
            < chunk.character_end
            <= len(parent.document_text)
        ):
            raise ValueError(
                f"{chunk.chunk_id}: invalid character offsets."
            )

        if (
            parent.document_text[
                chunk.character_start:chunk.character_end
            ]
            != chunk.chunk_text
        ):
            raise ValueError(
                f"{chunk.chunk_id}: chunk_text does not match parent slice."
            )

        if _sha256_text(chunk.chunk_text) != chunk.chunk_text_sha256:
            raise ValueError(
                f"{chunk.chunk_id}: chunk_text_sha256 mismatch."
            )

        grouped[chunk.document_version_id].append(chunk)

    for version_id, parent in expected_versions.items():
        parent_chunks = grouped[version_id]

        if not parent_chunks:
            raise ValueError(
                f"{parent.document_id}: no retrieval chunks were produced."
            )

        expected_indexes = list(range(len(parent_chunks)))
        actual_indexes = [
            chunk.chunk_index
            for chunk in parent_chunks
        ]
        if actual_indexes != expected_indexes:
            raise ValueError(
                f"{parent.document_id}: chunk indexes are not contiguous."
            )

        if parent_chunks[0].character_start != 0:
            raise ValueError(
                f"{parent.document_id}: first chunk must start at zero."
            )

        if parent_chunks[-1].character_end != len(parent.document_text):
            raise ValueError(
                f"{parent.document_id}: last chunk must end at document end."
            )

        previous_end = 0
        for chunk in parent_chunks:
            if chunk.character_start > previous_end:
                raise ValueError(
                    f"{parent.document_id}: chunk sequence leaves a gap."
                )
            previous_end = max(previous_end, chunk.character_end)


def _required_string(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
    ):
        raise ValueError(f"{field} must be a nonblank trimmed string.")
    return value


def _validate_sha256(value: object, field: str) -> str:
    normalized = _required_string(value, field).lower()
    if not SHA256_PATTERN.fullmatch(normalized):
        raise ValueError(
            f"{field} must contain exactly 64 hexadecimal characters."
        )
    return normalized


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_canonical(payload: dict[str, object]) -> str:
    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return _sha256_text(serialized)
