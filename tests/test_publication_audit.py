from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(
    0,
    str(PROJECT_ROOT / "src"),
)

from equity_research.publication_audit import (  # noqa: E402
    audit_publication_boundary,
    format_publication_findings,
)


class PublicationAuditTests(unittest.TestCase):
    def test_current_tracked_repository_passes_publication_audit(self) -> None:
        findings = audit_publication_boundary(
            PROJECT_ROOT
        )

        self.assertEqual(
            findings,
            (),
        )
        self.assertEqual(
            format_publication_findings(
                findings
            ),
            "PUBLICATION_BOUNDARY_AUDIT=PASSED",
        )

    def test_provider_data_export_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(
                temp_dir
            )
            path = root / "exports" / "news_responses.jsonl"
            path.parent.mkdir(
                parents=True
            )
            path.write_text(
                '{"synthetic": true}\n',
                encoding="utf-8",
            )

            findings = audit_publication_boundary(
                root,
                tracked_paths=(
                    "exports/news_responses.jsonl",
                ),
            )

        self.assertEqual(
            len(findings),
            1,
        )
        self.assertEqual(
            findings[0].rule,
            "provider_data_export",
        )

    def test_synthetic_test_fixture_path_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(
                temp_dir
            )
            path = (
                root
                / "tests"
                / "fixtures"
                / "news_articles.json"
            )
            path.parent.mkdir(
                parents=True
            )
            path.write_text(
                '{"synthetic": true}\n',
                encoding="utf-8",
            )

            findings = audit_publication_boundary(
                root,
                tracked_paths=(
                    "tests/fixtures/news_articles.json",
                ),
            )

        self.assertEqual(
            findings,
            (),
        )

    def test_credential_signature_is_rejected_without_echoing_secret(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(
                temp_dir
            )
            path = root / "scratch.py"
            secret = (
                "dapi"
                + ("A" * 40)
            )
            path.write_text(
                f'TOKEN = "{secret}"\n',
                encoding="utf-8",
            )

            findings = audit_publication_boundary(
                root,
                tracked_paths=(
                    "scratch.py",
                ),
            )
            rendered = format_publication_findings(
                findings
            )

        self.assertEqual(
            len(findings),
            1,
        )
        self.assertEqual(
            findings[0].rule,
            "databricks_pat",
        )
        self.assertNotIn(
            secret,
            rendered,
        )

    def test_portfolio_images_must_live_under_reviewed_docs_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(
                temp_dir
            )
            path = root / "app-live.png"
            path.write_bytes(
                b"synthetic-image"
            )

            findings = audit_publication_boundary(
                root,
                tracked_paths=(
                    "app-live.png",
                ),
            )

        self.assertEqual(
            len(findings),
            1,
        )
        self.assertEqual(
            findings[0].rule,
            "image_location",
        )


if __name__ == "__main__":
    unittest.main()
