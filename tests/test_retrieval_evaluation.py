import json
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from equity_research.retrieval_evaluation import (
    RetrievedChunk,
    RetrievalEvalCase,
    aggregate_case_metrics,
    duplicate_document_rate_at_k,
    evaluate_case,
    hit_at_k,
    reciprocal_rank,
    section_match_at_k,
    source_type_match_at_k,
    symbol_match_at_k,
    validate_eval_case,
)


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "retrieval_eval_cases.json"
)


def make_chunk(
    chunk_id: str,
    *,
    document_id: str | None = None,
    source_type: str = "filing",
    symbol: str = "MSFT",
    section_code: str | None = "item_1a",
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        document_id=document_id or f"doc:{chunk_id}",
        source_type=source_type,
        configured_symbols=(symbol,),
        section_code=section_code,
    )


class RetrievalEvaluationTests(unittest.TestCase):
    def test_fixture_contains_four_reviewed_cases(self):
        payload = json.loads(
            FIXTURE_PATH.read_text(encoding="utf-8")
        )

        self.assertEqual(
            payload["version"],
            "retrieval-eval-v1",
        )
        self.assertEqual(len(payload["cases"]), 4)

        case_ids = {
            case["case_id"]
            for case in payload["cases"]
        }

        self.assertEqual(len(case_ids), 4)

        for case in payload["cases"]:
            self.assertEqual(
                case["label_status"],
                "reviewed",
            )
            self.assertTrue(
                case["relevant_chunk_ids"]
            )

    def test_validate_eval_case_requires_labels(self):
        case = RetrievalEvalCase(
            case_id="R1",
            query="query",
            expected_symbol="MSFT",
            expected_source_type="filing",
            expected_section_code="item_1a",
            relevant_chunk_ids=frozenset(),
        )

        with self.assertRaises(ValueError):
            validate_eval_case(case)

    def test_hit_at_k_uses_any_reviewed_relevant_chunk(self):
        relevant = frozenset({"relevant-a", "relevant-b"})

        retrieved = (
            make_chunk("noise"),
            make_chunk("relevant-b"),
            make_chunk("other"),
        )

        self.assertEqual(
            hit_at_k(relevant, retrieved, 1),
            0.0,
        )
        self.assertEqual(
            hit_at_k(relevant, retrieved, 3),
            1.0,
        )

    def test_reciprocal_rank_uses_first_relevant_result(self):
        relevant = frozenset({"target"})

        retrieved = (
            make_chunk("noise-1"),
            make_chunk("noise-2"),
            make_chunk("target"),
        )

        self.assertAlmostEqual(
            reciprocal_rank(relevant, retrieved),
            1 / 3,
        )

    def test_reciprocal_rank_is_zero_when_no_label_matches(self):
        retrieved = (
            make_chunk("noise-1"),
            make_chunk("noise-2"),
        )

        self.assertEqual(
            reciprocal_rank(
                frozenset({"target"}),
                retrieved,
            ),
            0.0,
        )

    def test_symbol_match_at_k_is_fraction_of_returned_results(self):
        retrieved = (
            make_chunk("a", symbol="MSFT"),
            make_chunk("b", symbol="AAPL"),
            make_chunk("c", symbol="MSFT"),
        )

        self.assertAlmostEqual(
            symbol_match_at_k(
                "MSFT",
                retrieved,
                5,
            ),
            2 / 3,
        )

    def test_source_type_match_at_k(self):
        retrieved = (
            make_chunk(
                "a",
                source_type="filing",
            ),
            make_chunk(
                "b",
                source_type="news",
            ),
            make_chunk(
                "c",
                source_type="filing",
            ),
        )

        self.assertAlmostEqual(
            source_type_match_at_k(
                "filing",
                retrieved,
                5,
            ),
            2 / 3,
        )

    def test_section_match_is_none_when_not_expected(self):
        retrieved = (
            make_chunk(
                "a",
                source_type="news",
                section_code=None,
            ),
        )

        self.assertIsNone(
            section_match_at_k(
                None,
                retrieved,
                5,
            )
        )

    def test_duplicate_document_rate_counts_repeated_documents(self):
        retrieved = (
            make_chunk(
                "a",
                document_id="doc-1",
            ),
            make_chunk(
                "b",
                document_id="doc-1",
            ),
            make_chunk(
                "c",
                document_id="doc-2",
            ),
            make_chunk(
                "d",
                document_id="doc-2",
            ),
            make_chunk(
                "e",
                document_id="doc-3",
            ),
        )

        self.assertAlmostEqual(
            duplicate_document_rate_at_k(
                retrieved,
                5,
            ),
            2 / 5,
        )

    def test_evaluate_case_calculates_expected_metrics(self):
        case = RetrievalEvalCase(
            case_id="R1",
            query="query",
            expected_symbol="MSFT",
            expected_source_type="filing",
            expected_section_code="item_1a",
            relevant_chunk_ids=frozenset(
                {"target"}
            ),
        )

        retrieved = (
            make_chunk("noise"),
            make_chunk("target"),
            make_chunk("other"),
        )

        metrics = evaluate_case(
            case,
            retrieved,
        )

        self.assertEqual(metrics.hit_at_1, 0.0)
        self.assertEqual(metrics.hit_at_3, 1.0)
        self.assertEqual(metrics.hit_at_5, 1.0)
        self.assertEqual(
            metrics.reciprocal_rank,
            0.5,
        )
        self.assertEqual(
            metrics.symbol_match_at_5,
            1.0,
        )
        self.assertEqual(
            metrics.source_type_match_at_5,
            1.0,
        )
        self.assertEqual(
            metrics.section_match_at_5,
            1.0,
        )

    def test_aggregate_case_metrics_macro_averages(self):
        first_case = RetrievalEvalCase(
            case_id="R1",
            query="query",
            expected_symbol="MSFT",
            expected_source_type="filing",
            expected_section_code="item_1a",
            relevant_chunk_ids=frozenset(
                {"target"}
            ),
        )

        second_case = RetrievalEvalCase(
            case_id="R2",
            query="query",
            expected_symbol="AAPL",
            expected_source_type="news",
            expected_section_code=None,
            relevant_chunk_ids=frozenset(
                {"missing"}
            ),
        )

        first_metrics = evaluate_case(
            first_case,
            (
                make_chunk("target"),
            ),
        )

        second_metrics = evaluate_case(
            second_case,
            (
                make_chunk(
                    "noise",
                    source_type="news",
                    symbol="AAPL",
                    section_code=None,
                ),
            ),
        )

        suite = aggregate_case_metrics(
            (
                first_metrics,
                second_metrics,
            )
        )

        self.assertEqual(suite.case_count, 2)
        self.assertEqual(suite.hit_at_1, 0.5)
        self.assertEqual(suite.hit_at_3, 0.5)
        self.assertEqual(suite.hit_at_5, 0.5)
        self.assertEqual(
            suite.mean_reciprocal_rank,
            0.5,
        )
        self.assertEqual(
            suite.symbol_match_at_5,
            1.0,
        )
        self.assertEqual(
            suite.source_type_match_at_5,
            1.0,
        )
        self.assertEqual(
            suite.section_match_at_5,
            1.0,
        )


if __name__ == "__main__":
    unittest.main()
