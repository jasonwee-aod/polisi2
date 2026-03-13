"""Tests for state management and deduplication."""

import pytest
import tempfile
from pathlib import Path
from mohe_scraper.state_manager import StateManager
from mohe_scraper.models import StateRecord


@pytest.fixture
def temp_db():
    """Create temporary database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        yield str(db_path)


class TestStateManager:
    """Test deduplication state management."""

    def test_init_creates_database(self, temp_db):
        """Test that database is created on init."""
        manager = StateManager(temp_db)
        assert Path(temp_db).exists()

    def test_save_and_check_url(self, temp_db):
        """Test saving and retrieving records by URL."""
        manager = StateManager(temp_db)

        record = StateRecord(
            canonical_url="https://mohe.gov.my/test",
            sha256="abc123",
            http_etag="etag123",
            http_last_modified="2026-02-27",
            gcs_uri="gs://bucket/path",
            last_seen_at="2026-02-27T00:00:00Z",
            doc_type="announcement",
            title="Test Document"
        )

        manager.save_record(record)

        # Check if URL exists
        existing = manager.check_url_exists("https://mohe.gov.my/test")
        assert existing is not None
        assert existing.sha256 == "abc123"

    def test_check_nonexistent_url(self, temp_db):
        """Test checking non-existent URL."""
        manager = StateManager(temp_db)
        result = manager.check_url_exists("https://mohe.gov.my/nonexistent")
        assert result is None

    def test_save_and_check_hash(self, temp_db):
        """Test saving and retrieving records by hash."""
        manager = StateManager(temp_db)

        record = StateRecord(
            canonical_url="https://mohe.gov.my/test",
            sha256="hash123",
            http_etag=None,
            http_last_modified=None,
            gcs_uri="gs://bucket/path",
            last_seen_at="2026-02-27T00:00:00Z",
            doc_type="announcement",
            title="Test"
        )

        manager.save_record(record)

        # Check if hash exists
        existing = manager.check_hash_exists("hash123")
        assert existing is not None
        assert existing.canonical_url == "https://mohe.gov.my/test"

    def test_check_nonexistent_hash(self, temp_db):
        """Test checking non-existent hash."""
        manager = StateManager(temp_db)
        result = manager.check_hash_exists("nonexistent_hash")
        assert result is None

    def test_duplicate_url_raises_constraint(self, temp_db):
        """Test that duplicate URLs violate uniqueness constraint."""
        manager = StateManager(temp_db)

        record1 = StateRecord(
            canonical_url="https://mohe.gov.my/test",
            sha256="hash1",
            http_etag=None,
            http_last_modified=None,
            gcs_uri="gs://bucket/path1",
            last_seen_at="2026-02-27T00:00:00Z",
            doc_type="announcement",
            title="Test 1"
        )

        record2 = StateRecord(
            canonical_url="https://mohe.gov.my/test",
            sha256="hash2",
            http_etag=None,
            http_last_modified=None,
            gcs_uri="gs://bucket/path2",
            last_seen_at="2026-02-27T00:00:00Z",
            doc_type="announcement",
            title="Test 2"
        )

        manager.save_record(record1)
        # Second save should update, not insert
        manager.save_record(record2)

        existing = manager.check_url_exists("https://mohe.gov.my/test")
        assert existing.sha256 == "hash2"  # Should have updated

    def test_mark_inactive(self, temp_db):
        """Test marking records as inactive."""
        manager = StateManager(temp_db)

        record = StateRecord(
            canonical_url="https://mohe.gov.my/test",
            sha256="hash123",
            http_etag=None,
            http_last_modified=None,
            gcs_uri="gs://bucket/path",
            last_seen_at="2026-02-27T00:00:00Z",
            doc_type="announcement",
            title="Test",
            is_active=True
        )

        manager.save_record(record)
        manager.mark_inactive("https://mohe.gov.my/test")

        existing = manager.check_url_exists("https://mohe.gov.my/test")
        assert existing.is_active is False

    def test_get_stats(self, temp_db):
        """Test statistics retrieval."""
        manager = StateManager(temp_db)

        for i in range(5):
            record = StateRecord(
                canonical_url=f"https://mohe.gov.my/test{i}",
                sha256=f"hash{i}",
                http_etag=None,
                http_last_modified=None,
                gcs_uri=f"gs://bucket/path{i}",
                last_seen_at="2026-02-27T00:00:00Z",
                doc_type="announcement",
                title=f"Test {i}",
                is_active=True
            )
            manager.save_record(record)

        stats = manager.get_stats()
        assert stats["total_records"] == 5
        assert stats["active_records"] == 5

        # Mark one as inactive
        manager.mark_inactive("https://mohe.gov.my/test0")
        stats = manager.get_stats()
        assert stats["active_records"] == 4
        assert stats["inactive_records"] == 1
