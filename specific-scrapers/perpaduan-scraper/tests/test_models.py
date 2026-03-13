"""Tests for data models."""
import pytest
import json
from src.models import ScrapedRecord, CrawlRun


class TestScrapedRecord:
    def test_create_record(self):
        record = ScrapedRecord(
            source_url="https://perpaduan.gov.my/page",
            canonical_url="https://perpaduan.gov.my/page",
            title="Test Document",
            published_at="2026-03-09",
            agency="Kementerian Perpaduan Negara",
            doc_type="news",
            content_type="text/html",
            language="ms",
        )
        assert record.title == "Test Document"
        assert record.record_id is not None
        assert record.fetched_at is not None

    def test_to_json(self):
        record = ScrapedRecord(
            source_url="https://perpaduan.gov.my/page",
            canonical_url="https://perpaduan.gov.my/page",
            title="Test",
            published_at="2026-03-09",
            agency="KPN",
            doc_type="news",
            content_type="text/html",
            language="ms",
        )
        json_str = record.to_json()
        data = json.loads(json_str)
        assert data["title"] == "Test"
        assert "record_id" in data

    def test_to_dict(self):
        record = ScrapedRecord(
            source_url="https://perpaduan.gov.my/page",
            canonical_url="https://perpaduan.gov.my/page",
            title="Test",
            published_at="2026-03-09",
            agency="KPN",
            doc_type="news",
            content_type="text/html",
            language="ms",
        )
        data = record.to_dict()
        assert isinstance(data, dict)
        assert data["title"] == "Test"


class TestCrawlRun:
    def test_create_run(self):
        run = CrawlRun(
            crawl_run_id="2026-03-09-perpaduan",
            site_slug="perpaduan",
            started_at="2026-03-09T12:00:00Z",
            discovered=100,
            fetched=95,
            uploaded=90,
            deduped=5,
            failed=0,
        )
        assert run.discovered == 100
        assert run.failed == 0

    def test_to_json(self):
        run = CrawlRun(
            crawl_run_id="2026-03-09-perpaduan",
            site_slug="perpaduan",
            started_at="2026-03-09T12:00:00Z",
        )
        json_str = run.to_json()
        data = json.loads(json_str)
        assert data["crawl_run_id"] == "2026-03-09-perpaduan"
