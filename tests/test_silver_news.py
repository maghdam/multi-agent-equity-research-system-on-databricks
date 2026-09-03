import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_research.silver_news import (
    BronzeNewsResponse,
    SilverNewsCandidate,
    select_current_news_versions,
    transform_news_response,
    transform_news_snapshot,
)

class SilverNewsTransformationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fetched_at = datetime(
            2026,
            9,
            3,
            12,
            0,
            tzinfo=timezone.utc,
        )

    def _bronze_response(
        self,
        *,
        articles: list[dict[str, object]],
        source_response_id: str = "response-001",
        fetched_at: datetime | None = None,
        ingestion_run_id: str = "run-001",
    ) -> BronzeNewsResponse:
        payload = {
            "news": articles,
            "next_page_token": None,
        }

        return BronzeNewsResponse(
            source_system="alpaca",
            source_response_id=source_response_id,
            response_payload_json=json.dumps(payload),
            fetched_at=fetched_at or self.fetched_at,
            ingestion_run_id=ingestion_run_id,
        )



    def test_snapshot_selects_newest_in_scope_revision(
        self,
    ) -> None:
        older = self._bronze_response(
            articles=[
                self._article(
                    headline="Older headline",
                    symbols=["AAPL"],
                    updated_at="2026-09-03T09:30:00Z",
                )
            ],
            source_response_id="response-001",
        )

        newer = self._bronze_response(
            articles=[
                self._article(
                    headline="Current headline",
                    symbols=["MSFT"],
                    updated_at="2026-09-03T10:30:00Z",
                )
            ],
            source_response_id="response-002",
        )

        result = transform_news_snapshot(
            bronze_responses=[older, newer],
            configured_symbols=["AAPL", "MSFT"],
        )

        self.assertEqual(result.selected_count, 1)
        self.assertEqual(
            result.selected[0].headline,
            "Current headline",
        )
        self.assertEqual(
            result.selected[0].configured_symbols,
            ("MSFT",),
        )
        self.assertEqual(result.superseded_count, 1)

    def test_snapshot_removes_outdated_symbol_relationship(
        self,
    ) -> None:
        older = self._bronze_response(
            articles=[
                self._article(
                    symbols=["AAPL"],
                    updated_at="2026-09-03T09:30:00Z",
                )
            ],
            source_response_id="response-001",
        )

        newer = self._bronze_response(
            articles=[
                self._article(
                    symbols=["NVDA"],
                    updated_at="2026-09-03T10:30:00Z",
                )
            ],
            source_response_id="response-002",
        )

        result = transform_news_snapshot(
            bronze_responses=[older, newer],
            configured_symbols=["AAPL", "MSFT"],
        )

        self.assertEqual(result.selected_count, 0)
        self.assertEqual(result.out_of_scope_count, 1)
        self.assertEqual(result.superseded_count, 1)

    def test_snapshot_configured_symbols_are_unique_and_deterministic(
        self,
    ) -> None:
        response = self._bronze_response(
            articles=[
                self._article(
                    symbols=[
                        "MSFT",
                        "NVDA",
                        "AAPL",
                        "AAPL",
                    ]
                )
            ]
        )

        result = transform_news_snapshot(
            bronze_responses=[response],
            configured_symbols=["AAPL", "MSFT"],
        )

        self.assertEqual(result.selected_count, 1)

        article = result.selected[0]

        self.assertEqual(
            article.symbols,
            ("MSFT", "NVDA", "AAPL", "AAPL"),
        )
        self.assertEqual(
            article.configured_symbols,
            ("AAPL", "MSFT"),
        )

    def test_snapshot_aggregates_rejected_observations(
        self,
    ) -> None:
        response = self._bronze_response(
            articles=[
                self._article(),
                self._article(
                    id="invalid-id",
                ),
            ]
        )

        result = transform_news_snapshot(
            bronze_responses=[response],
            configured_symbols=["AAPL", "MSFT"],
        )

        self.assertEqual(
            result.accepted_candidate_count,
            1,
        )
        self.assertEqual(result.rejected_count, 1)
        self.assertEqual(result.selected_count, 1)

    def test_snapshot_counts_duplicates_and_superseded_versions(
        self,
    ) -> None:
        older = self._bronze_response(
            articles=[
                self._article(
                    headline="Older headline",
                    updated_at="2026-09-03T09:00:00Z",
                )
            ],
            source_response_id="response-001",
        )

        current_first = self._bronze_response(
            articles=[
                self._article(
                    updated_at="2026-09-03T10:00:00Z",
                )
            ],
            source_response_id="response-002",
            fetched_at=datetime(
                2026,
                9,
                3,
                11,
                0,
                tzinfo=timezone.utc,
            ),
        )

        current_repeat = self._bronze_response(
            articles=[
                self._article(
                    updated_at="2026-09-03T10:00:00Z",
                )
            ],
            source_response_id="response-003",
            fetched_at=datetime(
                2026,
                9,
                3,
                11,
                30,
                tzinfo=timezone.utc,
            ),
        )

        result = transform_news_snapshot(
            bronze_responses=[
                older,
                current_first,
                current_repeat,
            ],
            configured_symbols=["AAPL", "MSFT"],
        )

        self.assertEqual(
            result.accepted_candidate_count,
            3,
        )
        self.assertEqual(result.selected_count, 1)
        self.assertEqual(result.duplicate_count, 1)
        self.assertEqual(result.superseded_count, 1)
        self.assertEqual(
            result.selected[0].source_response_id,
            "response-002",
        )

    def test_snapshot_fails_on_cross_response_current_conflict(
        self,
    ) -> None:
        first = self._bronze_response(
            articles=[
                self._article(
                    headline="Headline A",
                )
            ],
            source_response_id="response-001",
        )

        second = self._bronze_response(
            articles=[
                self._article(
                    headline="Headline B",
                )
            ],
            source_response_id="response-002",
        )

        with self.assertRaises(ValueError):
            transform_news_snapshot(
                bronze_responses=[first, second],
                configured_symbols=["AAPL", "MSFT"],
            )

    def test_snapshot_fails_if_bronze_response_is_malformed(
        self,
    ) -> None:
        valid = self._bronze_response(
            articles=[self._article()]
        )

        malformed = BronzeNewsResponse(
            source_system="alpaca",
            source_response_id="response-002",
            response_payload_json=json.dumps(
                {"unexpected": []}
            ),
            fetched_at=self.fetched_at,
            ingestion_run_id="run-002",
        )

        with self.assertRaises(ValueError):
            transform_news_snapshot(
                bronze_responses=[valid, malformed],
                configured_symbols=["AAPL", "MSFT"],
            )

    def test_invalid_newer_observation_does_not_replace_valid_version(
        self,
    ) -> None:
        older_valid = self._bronze_response(
            articles=[
                self._article(
                    headline="Valid version",
                    updated_at="2026-09-03T09:30:00Z",
                )
            ],
            source_response_id="response-001",
        )

        newer_invalid = self._bronze_response(
            articles=[
                self._article(
                    headline="Invalid newer version",
                    updated_at="2026-09-03T12:00:01Z",
                )
            ],
            source_response_id="response-002",
        )

        result = transform_news_snapshot(
            bronze_responses=[
                older_valid,
                newer_invalid,
            ],
            configured_symbols=["AAPL", "MSFT"],
        )

        self.assertEqual(result.rejected_count, 1)
        self.assertEqual(result.selected_count, 1)
        self.assertEqual(
            result.selected[0].headline,
            "Valid version",
        )

    def _candidate(
        self,
        *,
        article_id: int = 123456789,
        headline: str = "Apple announces a product update",
        symbols: tuple[str, ...] = ("AAPL",),
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
        article_source: str = "Benzinga",
        url: str = "https://example.com/news/123456789",
        summary: str | None = "A short summary.",
        content: str | None = "<p>Article content.</p>",
        source_response_id: str = "response-001",
        fetched_at: datetime | None = None,
        ingestion_run_id: str = "run-001",
    ) -> SilverNewsCandidate:
        return SilverNewsCandidate(
            source_system="alpaca",
            article_id=article_id,
            headline=headline,
            symbols=symbols,
            article_created_at=created_at
            or datetime(
                2026,
                9,
                3,
                9,
                0,
                tzinfo=timezone.utc,
            ),
            article_updated_at=updated_at
            or datetime(
                2026,
                9,
                3,
                10,
                0,
                tzinfo=timezone.utc,
            ),
            article_source=article_source,
            url=url,
            summary=summary,
            content=content,
            source_response_id=source_response_id,
            fetched_at=fetched_at or self.fetched_at,
            ingestion_run_id=ingestion_run_id,
        )

    def test_newer_article_revision_wins(self) -> None:
        older = self._candidate(
            headline="Older headline",
            updated_at=datetime(
                2026,
                9,
                3,
                10,
                0,
                tzinfo=timezone.utc,
            ),
            fetched_at=datetime(
                2026,
                9,
                3,
                11,
                30,
                tzinfo=timezone.utc,
            ),
        )

        newer = self._candidate(
            headline="Newer headline",
            updated_at=datetime(
                2026,
                9,
                3,
                11,
                0,
                tzinfo=timezone.utc,
            ),
            fetched_at=datetime(
                2026,
                9,
                3,
                11,
                15,
                tzinfo=timezone.utc,
            ),
            source_response_id="response-002",
        )

        result = select_current_news_versions(
            [older, newer]
        )

        self.assertEqual(result.selected_count, 1)
        self.assertEqual(
            result.selected[0].headline,
            "Newer headline",
        )
        self.assertEqual(result.superseded_count, 1)
        self.assertEqual(result.duplicate_count, 0)

    def test_later_fetch_cannot_replace_newer_revision(self) -> None:
        newer_revision = self._candidate(
            updated_at=datetime(
                2026,
                9,
                3,
                11,
                0,
                tzinfo=timezone.utc,
            ),
            fetched_at=datetime(
                2026,
                9,
                3,
                11,
                30,
                tzinfo=timezone.utc,
            ),
        )

        older_revision_fetched_later = self._candidate(
            headline="Older revision",
            updated_at=datetime(
                2026,
                9,
                3,
                10,
                0,
                tzinfo=timezone.utc,
            ),
            fetched_at=datetime(
                2026,
                9,
                3,
                12,
                0,
                tzinfo=timezone.utc,
            ),
            source_response_id="response-002",
        )

        result = select_current_news_versions(
            [
                newer_revision,
                older_revision_fetched_later,
            ]
        )

        self.assertEqual(
            result.selected[0].article_updated_at,
            newer_revision.article_updated_at,
        )
        self.assertEqual(result.superseded_count, 1)

    def test_identical_current_repeats_use_earliest_provenance(
        self,
    ) -> None:
        later_fetch = self._candidate(
            fetched_at=datetime(
                2026,
                9,
                3,
                12,
                0,
                tzinfo=timezone.utc,
            ),
            source_response_id="response-001",
            ingestion_run_id="run-001",
        )

        earlier_fetch = self._candidate(
            fetched_at=datetime(
                2026,
                9,
                3,
                11,
                30,
                tzinfo=timezone.utc,
            ),
            source_response_id="response-999",
            ingestion_run_id="run-999",
        )

        result = select_current_news_versions(
            [later_fetch, earlier_fetch]
        )

        self.assertEqual(
            result.selected[0].source_response_id,
            "response-999",
        )
        self.assertEqual(result.duplicate_count, 1)

    def test_same_update_symbol_order_and_repeats_are_identical(
        self,
    ) -> None:
        first = self._candidate(
            symbols=("AAPL", "MSFT"),
            source_response_id="response-002",
        )

        second = self._candidate(
            symbols=("MSFT", "AAPL", "AAPL"),
            source_response_id="response-001",
        )

        result = select_current_news_versions(
            [first, second]
        )

        self.assertEqual(result.selected_count, 1)
        self.assertEqual(result.duplicate_count, 1)

    def test_current_version_content_conflict_fails(self) -> None:
        first = self._candidate(
            headline="Headline A",
        )

        second = self._candidate(
            headline="Headline B",
            source_response_id="response-002",
        )

        with self.assertRaises(ValueError):
            select_current_news_versions(
                [first, second]
            )

    def test_older_conflict_does_not_block_newer_revision(
        self,
    ) -> None:
        older_a = self._candidate(
            headline="Old headline A",
            updated_at=datetime(
                2026,
                9,
                3,
                9,
                30,
                tzinfo=timezone.utc,
            ),
        )

        older_b = self._candidate(
            headline="Old headline B",
            updated_at=datetime(
                2026,
                9,
                3,
                9,
                30,
                tzinfo=timezone.utc,
            ),
            source_response_id="response-002",
        )

        newer = self._candidate(
            headline="Current headline",
            updated_at=datetime(
                2026,
                9,
                3,
                10,
                30,
                tzinfo=timezone.utc,
            ),
            source_response_id="response-003",
        )

        result = select_current_news_versions(
            [older_a, older_b, newer]
        )

        self.assertEqual(result.selected_count, 1)
        self.assertEqual(
            result.selected[0].headline,
            "Current headline",
        )
        self.assertEqual(result.superseded_count, 2)
        self.assertEqual(result.duplicate_count, 0)

    def _article(
        self,
        **overrides: object,
    ) -> dict[str, object]:
        article: dict[str, object] = {
            "id": 123456789,
            "headline": "Apple announces a product update",
            "symbols": ["AAPL", "MSFT"],
            "created_at": "2026-09-03T09:00:00Z",
            "updated_at": "2026-09-03T10:00:00Z",
            "source": "Benzinga",
            "url": "https://example.com/news/123456789",
            "summary": "A short summary.",
            "content": "<p>Article content.</p>",
        }

        article.update(overrides)
        return article

    def _transform(
        self,
        article: dict[str, object],
        *,
        fetched_at: datetime | None = None,
    ):
        payload = {
            "news": [article],
            "next_page_token": None,
        }

        return transform_news_response(
            response_payload_json=json.dumps(payload),
            source_system="alpaca",
            source_response_id="response-001",
            fetched_at=fetched_at or self.fetched_at,
            ingestion_run_id="run-001",
        )

    def _issue_codes(self, result) -> set[str]:
        return {
            issue.code
            for rejected in result.rejected
            for issue in rejected.issues
        }

    def test_accepts_valid_article(self) -> None:
        result = self._transform(self._article())

        self.assertEqual(result.accepted_count, 1)
        self.assertEqual(result.rejected_count, 0)

        candidate = result.accepted[0]

        self.assertEqual(candidate.source_system, "alpaca")
        self.assertEqual(candidate.article_id, 123456789)
        self.assertEqual(
            candidate.headline,
            "Apple announces a product update",
        )
        self.assertEqual(
            candidate.symbols,
            ("AAPL", "MSFT"),
        )
        self.assertEqual(
            candidate.article_created_at,
            datetime(
                2026,
                9,
                3,
                9,
                0,
                tzinfo=timezone.utc,
            ),
        )
        self.assertEqual(
            candidate.article_updated_at,
            datetime(
                2026,
                9,
                3,
                10,
                0,
                tzinfo=timezone.utc,
            ),
        )
        self.assertEqual(candidate.article_source, "Benzinga")
        self.assertEqual(
            candidate.url,
            "https://example.com/news/123456789",
        )
        self.assertEqual(candidate.summary, "A short summary.")
        self.assertEqual(
            candidate.content,
            "<p>Article content.</p>",
        )
        self.assertEqual(
            candidate.source_response_id,
            "response-001",
        )
        self.assertEqual(candidate.fetched_at, self.fetched_at)
        self.assertEqual(candidate.ingestion_run_id, "run-001")

    def test_missing_optional_text_keeps_metadata(self) -> None:
        result = self._transform(
            self._article(
                summary=None,
                content="   ",
            )
        )

        self.assertEqual(result.accepted_count, 1)
        self.assertEqual(result.rejected_count, 0)

        candidate = result.accepted[0]

        self.assertIsNone(candidate.summary)
        self.assertIsNone(candidate.content)

    def test_accepts_empty_symbol_list(self) -> None:
        result = self._transform(
            self._article(symbols=[])
        )

        self.assertEqual(result.accepted_count, 1)
        self.assertEqual(
            result.accepted[0].symbols,
            (),
        )

    def test_preserves_repeated_symbol_tags(self) -> None:
        result = self._transform(
            self._article(
                symbols=["AAPL", "MSFT", "AAPL"],
            )
        )

        self.assertEqual(result.accepted_count, 1)
        self.assertEqual(
            result.accepted[0].symbols,
            ("AAPL", "MSFT", "AAPL"),
        )

    def test_rejects_noninteger_article_id(self) -> None:
        result = self._transform(
            self._article(id="123456789")
        )

        self.assertEqual(result.accepted_count, 0)
        self.assertEqual(result.rejected_count, 1)
        self.assertIn(
            "invalid_article_id",
            self._issue_codes(result),
        )

    def test_rejects_boolean_article_id(self) -> None:
        result = self._transform(
            self._article(id=True)
        )

        self.assertEqual(result.accepted_count, 0)
        self.assertIn(
            "invalid_article_id",
            self._issue_codes(result),
        )

    def test_rejects_blank_symbol_tag(self) -> None:
        result = self._transform(
            self._article(
                symbols=["AAPL", "   "],
            )
        )

        self.assertEqual(result.accepted_count, 0)
        self.assertIn(
            "invalid_symbol_tag",
            self._issue_codes(result),
        )

    def test_rejects_created_after_updated(self) -> None:
        result = self._transform(
            self._article(
                created_at="2026-09-03T11:00:00Z",
                updated_at="2026-09-03T10:00:00Z",
            )
        )

        self.assertEqual(result.accepted_count, 0)
        self.assertIn(
            "created_after_updated",
            self._issue_codes(result),
        )

    def test_rejects_updated_after_fetched(self) -> None:
        result = self._transform(
            self._article(
                updated_at="2026-09-03T12:00:01Z",
            )
        )

        self.assertEqual(result.accepted_count, 0)
        self.assertIn(
            "updated_after_fetched",
            self._issue_codes(result),
        )

    def test_rejects_non_http_citation_url(self) -> None:
        result = self._transform(
            self._article(
                url="ftp://example.com/news/123456789",
            )
        )

        self.assertEqual(result.accepted_count, 0)
        self.assertIn(
            "invalid_citation_url",
            self._issue_codes(result),
        )

    def test_rejects_citation_url_with_credentials(self) -> None:
        result = self._transform(
            self._article(
                url="https://user:password@example.com/article",
            )
        )

        self.assertEqual(result.accepted_count, 0)
        self.assertIn(
            "invalid_citation_url",
            self._issue_codes(result),
        )

    def test_rejects_naive_article_timestamp(self) -> None:
        result = self._transform(
            self._article(
                updated_at="2026-09-03T10:00:00",
            )
        )

        self.assertEqual(result.accepted_count, 0)
        self.assertIn(
            "timezone_required",
            self._issue_codes(result),
        )

    def test_malformed_news_envelope_fails_response(self) -> None:
        with self.assertRaises(ValueError):
            transform_news_response(
                response_payload_json=json.dumps(
                    {
                        "unexpected": [],
                        "next_page_token": None,
                    }
                ),
                source_system="alpaca",
                source_response_id="response-001",
                fetched_at=self.fetched_at,
                ingestion_run_id="run-001",
            )

    def test_requires_timezone_aware_fetched_at(self) -> None:
        naive_fetched_at = self.fetched_at.replace(
            tzinfo=None
        )

        with self.assertRaises(ValueError):
            self._transform(
                self._article(),
                fetched_at=naive_fetched_at,
            )


if __name__ == "__main__":
    unittest.main()