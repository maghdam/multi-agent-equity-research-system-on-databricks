"""Offline tests for the live retrieval-evaluation runner boundary."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = (
    PROJECT_ROOT
    / "scripts"
    / "run_live_retrieval_evaluation.py"
)

spec = importlib.util.spec_from_file_location(
    "run_live_retrieval_evaluation",
    SCRIPT_PATH,
)

if spec is None or spec.loader is None:
    raise RuntimeError(
        "Could not load live retrieval evaluation script."
    )

live_runner = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = live_runner
spec.loader.exec_module(live_runner)


class LiveRetrievalEvaluationTests(unittest.TestCase):
    def test_load_cases_reads_four_reviewed_cases(self):
        cases = live_runner.load_cases(
            live_runner.DEFAULT_FIXTURE_PATH
        )

        self.assertEqual(len(cases), 4)

        self.assertEqual(
            tuple(case.case_id for case in cases),
            (
                "R1_MSFT_AI_CYBER_RISK",
                "R2_AAPL_SUPPLY_CHAIN_RISK",
                "R3_MSFT_RECENT_DEVELOPMENT",
                "R4_AAPL_RECENT_DEVELOPMENT",
            ),
        )

        for case in cases:
            self.assertTrue(case.relevant_chunk_ids)

    def test_parse_retrieved_chunks_maps_vector_response(self):
        response = {
            "manifest": {
                "columns": [
                    {"name": "chunk_id"},
                    {"name": "document_id"},
                    {"name": "source_type"},
                    {"name": "configured_symbols"},
                    {"name": "section_code"},
                    {"name": "score"},
                ]
            },
            "result": {
                "data_array": [
                    [
                        "chunk-1",
                        "doc-1",
                        "filing",
                        ["MSFT"],
                        "item_1a",
                        0.75,
                    ]
                ]
            },
        }

        chunks = live_runner.parse_retrieved_chunks(
            response
        )

        self.assertEqual(len(chunks), 1)

        chunk = chunks[0]

        self.assertEqual(chunk.chunk_id, "chunk-1")
        self.assertEqual(chunk.document_id, "doc-1")
        self.assertEqual(chunk.source_type, "filing")
        self.assertEqual(
            chunk.configured_symbols,
            ("MSFT",),
        )
        self.assertEqual(
            chunk.section_code,
            "item_1a",
        )

    def test_parse_retrieved_chunks_preserves_multi_symbol_metadata(
        self,
    ):
        response = {
            "manifest": {
                "columns": [
                    {"name": "chunk_id"},
                    {"name": "document_id"},
                    {"name": "source_type"},
                    {"name": "configured_symbols"},
                    {"name": "section_code"},
                ]
            },
            "result": {
                "data_array": [
                    [
                        "chunk-2",
                        "doc-2",
                        "news",
                        ["AAPL", "MSFT"],
                        None,
                    ]
                ]
            },
        }

        chunks = live_runner.parse_retrieved_chunks(
            response
        )

        self.assertEqual(
            chunks[0].configured_symbols,
            ("AAPL", "MSFT"),
        )
        self.assertIsNone(
            chunks[0].section_code
        )

    def test_query_index_rejects_too_few_results_before_cli_call(
        self,
    ):
        with self.assertRaises(ValueError):
            live_runner.query_index(
                index_name="catalog.schema.index",
                profile="profile",
                query_text="query",
                query_type="ANN",
                num_results=4,
            )


if __name__ == "__main__":
    unittest.main()
