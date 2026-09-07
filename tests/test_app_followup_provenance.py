from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_research.app_followup import (  # noqa: E402
    FollowupAnswerContractError,
    validate_followup_output,
)


EVIDENCE_ID = "a" * 64
FINDING_SOURCE_ID = "recent_developments:AAPL:fd1"
EVIDENCE_SOURCE_ID = f"evidence:{EVIDENCE_ID}"


def _session_payload() -> dict:
    return {
        "version": 1,
        "research": {
            "mode": "single_company",
            "symbols": ["AAPL"],
            "market_window_sessions": 60,
            "report_status": "ready",
            "synthesis_mode": "model",
        },
        "sources": [
            {
                "source_id": FINDING_SOURCE_ID,
                "source_type": "worker_finding",
                "symbols": ["AAPL"],
                "text": (
                    "Apple announced a device leasing strategy."
                ),
                "evidence_ids": [EVIDENCE_ID],
            },
            {
                "source_id": EVIDENCE_SOURCE_ID,
                "source_type": "evidence_metadata",
                "symbols": ["AAPL"],
                "text": (
                    "AAPL · Alpaca/Benzinga news · dated 2026-08-30 · "
                    "from www.benzinga.com · source record 101"
                ),
                "evidence_ids": [EVIDENCE_ID],
            },
        ],
        "evidence": [
            {
                "evidence_id": EVIDENCE_ID,
                "short_evidence_id": "aaaaaaaaaaaa…",
                "source_label": "Alpaca/Benzinga news",
                "symbols": ["AAPL"],
                "evidence_date": "2026-08-30",
                "source_domain": "www.benzinga.com",
                "source_url": "https://www.benzinga.com/news/example",
                "source_business_id": "101",
                "section_label": None,
            }
        ],
        "conversation": [],
    }


class AppFollowupProvenanceTests(unittest.TestCase):
    def test_equivalent_natural_language_provenance_date_is_grounded(self) -> None:
        result = validate_followup_output(
            {
                "answer": (
                    "The supporting Benzinga source was published on "
                    "August 30, 2026."
                ),
                "source_ids": [FINDING_SOURCE_ID],
                "evidence_ids": [EVIDENCE_ID],
                "limitation": "",
            },
            session_payload=_session_payload(),
        )

        self.assertEqual(
            result.source_ids,
            (FINDING_SOURCE_ID,),
        )
        self.assertEqual(
            result.evidence_ids,
            (EVIDENCE_ID,),
        )

    def test_different_natural_language_provenance_date_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            FollowupAnswerContractError,
            "unsupported date",
        ):
            validate_followup_output(
                {
                    "answer": (
                        "The supporting Benzinga source was published on "
                        "August 31, 2026."
                    ),
                    "source_ids": [FINDING_SOURCE_ID],
                    "evidence_ids": [EVIDENCE_ID],
                    "limitation": "",
                },
                session_payload=_session_payload(),
            )


if __name__ == "__main__":
    unittest.main()
