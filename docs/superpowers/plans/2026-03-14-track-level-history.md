# Track-Level Download History Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace album-level download history with per-track recording that captures YouTube source metadata, supports multiple attempts, and shows expandable track details in the UI.

**Architecture:** New `track_downloads` table replaces `download_history` + `failed_tracks`. Album views are derived via GROUP BY. `download_track_youtube()` returns a metadata dict instead of `True`/string. All `add_log()` calls drop the `failed_tracks` parameter. UI shows album rows that expand to reveal per-track grids.

**Tech Stack:** Python 3.13, Flask, SQLite, yt-dlp, Jinja2, vanilla JS

**Spec:** `docs/superpowers/specs/2026-03-14-track-level-history-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `db.py` | Modify | Bump SCHEMA_VERSION to 2, add `_migrate_v1_to_v2()` |
| `models.py` | Modify | Replace history/failed-tracks functions with track_downloads CRUD |
| `downloader.py` | Modify | Change `download_track_youtube()` return type to metadata dict |
| `processing.py` | Modify | Record per-track downloads inline, drop `save_failed_tracks`/`add_history_entry` |
| `app.py` | Modify | Update routes for new data shape, add tracks endpoint |
| `templates/downloads.html` | Modify | Expandable album rows with track detail grid |
| `tests/test_db.py` | Modify | Add V1-to-V2 migration tests |
| `tests/test_models.py` | Modify | Replace old tests with track_downloads tests |
| `tests/test_downloader.py` | Modify | Test new return type from `download_track_youtube` |
| `tests/test_processing.py` | Create | Test `_download_tracks` calls `add_track_download` per track |
| `tests/test_routes.py` | Modify | Update history/failed/logs route tests for new shapes |

---

## Chunk 1: Database Migration (db.py)

### Task 1: Write V1-to-V2 migration tests

**Files:**
- Modify: `tests/test_db.py`

- [ ] **Step 1: Write migration test -- tables created and old tables dropped**

```python
def test_migrate_v1_to_v2_creates_track_downloads(temp_db):
    """V1 schema migrates to V2: old tables dropped, new table created."""
    import sqlite3

    init_db()  # creates V1
    conn = sqlite3.connect(temp_db)

    # Verify V1 tables exist
    tables = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "download_history" in tables
    assert "failed_tracks" in tables
    conn.close()

    # Bump to V2 by re-importing after patching
    close_db()
    import db as db_mod
    db_mod.SCHEMA_VERSION = 2
    db_mod.init_db()

    conn2 = sqlite3.connect(temp_db)
    tables2 = {
        row[0] for row in conn2.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "track_downloads" in tables2
    assert "download_history" not in tables2
    assert "failed_tracks" not in tables2
    # download_logs should still exist (recreated without failed_tracks col)
    assert "download_logs" in tables2

    # Verify schema version is 2
    row = conn2.execute(
        "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
    ).fetchone()
    assert row[0] == 2

    conn2.close()
    db_mod.SCHEMA_VERSION = 1  # restore for other tests
```

- [ ] **Step 2: Write migration test -- download_logs recreated without failed_tracks column**

```python
def test_migrate_v1_to_v2_logs_no_failed_tracks_col(temp_db):
    """After V2 migration, download_logs has no failed_tracks column."""
    import sqlite3

    init_db()
    close_db()
    import db as db_mod
    db_mod.SCHEMA_VERSION = 2
    db_mod.init_db()

    conn = sqlite3.connect(temp_db)
    cols = [
        row[1] for row in conn.execute("PRAGMA table_info(download_logs)")
    ]
    assert "failed_tracks" not in cols
    assert "type" in cols
    assert "details" in cols
    conn.close()
    db_mod.SCHEMA_VERSION = 1
```

- [ ] **Step 3: Write migration test -- track_downloads indexes exist**

```python
def test_migrate_v1_to_v2_indexes(temp_db):
    """V2 migration creates all expected indexes on track_downloads."""
    import sqlite3

    init_db()
    close_db()
    import db as db_mod
    db_mod.SCHEMA_VERSION = 2
    db_mod.init_db()

    conn = sqlite3.connect(temp_db)
    indexes = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
            " AND tbl_name='track_downloads'"
        ).fetchall()
    }
    assert "idx_track_dl_album_id" in indexes
    assert "idx_track_dl_album_id_success" in indexes
    assert "idx_track_dl_timestamp" in indexes
    assert "idx_track_dl_youtube_url" in indexes
    conn.close()
    db_mod.SCHEMA_VERSION = 1
```

- [ ] **Step 4: Write migration test -- rollback on failure**

```python
def test_migrate_v1_to_v2_rollback_on_failure(temp_db):
    """If migration fails mid-way, V1 schema stays intact."""
    import sqlite3
    from unittest.mock import patch

    init_db()
    close_db()
    import db as db_mod
    db_mod.SCHEMA_VERSION = 2

    # Make the migration fail by patching executescript to raise
    original_execute = sqlite3.Connection.execute

    call_count = [0]
    def failing_execute(self, sql, *args, **kwargs):
        # Fail on CREATE TABLE track_downloads
        if "track_downloads" in sql and "CREATE" in sql:
            raise sqlite3.OperationalError("simulated failure")
        return original_execute(self, sql, *args, **kwargs)

    with patch.object(sqlite3.Connection, "execute", failing_execute):
        try:
            db_mod.init_db()
        except sqlite3.OperationalError:
            pass

    conn = sqlite3.connect(temp_db)
    tables = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    # V1 tables should still exist
    assert "download_history" in tables
    assert "failed_tracks" in tables
    assert "track_downloads" not in tables

    version = conn.execute(
        "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
    ).fetchone()
    assert version[0] == 1
    conn.close()
    db_mod.SCHEMA_VERSION = 1
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `source .venv/bin/activate && python3 -m pytest tests/test_db.py -v -k "v1_to_v2"`
Expected: FAIL -- migration functions don't exist yet

- [ ] **Step 6: Commit test stubs**

```bash
git add tests/test_db.py
git commit -m "test: add V1-to-V2 migration tests for track_downloads"
```

### Task 2: Implement V1-to-V2 migration

**Files:**
- Modify: `db.py`

- [ ] **Step 1: Add migration function and update SCHEMA_VERSION**

In `db.py`, change `SCHEMA_VERSION = 1` to `SCHEMA_VERSION = 2` and add the migration function.

The migration function to add before `_run_migrations`:

```python
def _migrate_v1_to_v2(conn):
    """Replace download_history + failed_tracks with track_downloads.

    Runs inside the transaction managed by _run_migrations. Drops all
    old data (no track-level info to preserve) and recreates download_logs
    without the failed_tracks column.
    """
    conn.execute("DROP TABLE IF EXISTS download_history")
    conn.execute("DROP TABLE IF EXISTS failed_tracks")
    conn.execute("DROP TABLE IF EXISTS download_logs")

    conn.execute("""
        CREATE TABLE track_downloads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            album_id INTEGER NOT NULL,
            album_title TEXT NOT NULL,
            artist_name TEXT NOT NULL,
            track_title TEXT NOT NULL,
            track_number INTEGER NOT NULL DEFAULT 0,
            success INTEGER NOT NULL DEFAULT 0,
            error_message TEXT DEFAULT '',
            youtube_url TEXT DEFAULT '',
            youtube_title TEXT DEFAULT '',
            match_score REAL DEFAULT 0.0,
            duration_seconds INTEGER DEFAULT 0,
            album_path TEXT DEFAULT '',
            lidarr_album_path TEXT DEFAULT '',
            cover_url TEXT DEFAULT '',
            timestamp REAL NOT NULL
        )
    """)

    conn.execute(
        "CREATE INDEX idx_track_dl_album_id"
        " ON track_downloads(album_id)"
    )
    conn.execute(
        "CREATE INDEX idx_track_dl_album_id_success"
        " ON track_downloads(album_id, success)"
    )
    conn.execute(
        "CREATE INDEX idx_track_dl_timestamp"
        " ON track_downloads(timestamp)"
    )
    conn.execute(
        "CREATE INDEX idx_track_dl_youtube_url"
        " ON track_downloads(youtube_url)"
    )

    conn.execute("""
        CREATE TABLE download_logs (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            album_id INTEGER NOT NULL,
            album_title TEXT NOT NULL,
            artist_name TEXT NOT NULL,
            timestamp REAL NOT NULL,
            details TEXT DEFAULT '',
            total_file_size INTEGER DEFAULT 0
        )
    """)

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_logs_timestamp"
        " ON download_logs(timestamp)"
    )
```

Then update the `migrations` dict inside `_run_migrations`:

```python
    migrations = {
        2: _migrate_v1_to_v2,
    }
```

Also wrap the migration call in a transaction with rollback. Replace `_run_migrations`:

```python
def _run_migrations(conn, current_version):
    """Run any pending schema migrations sequentially."""
    migrations = {
        2: _migrate_v1_to_v2,
    }
    for version in sorted(migrations):
        if current_version < version:
            logger.info("Running migration to schema version %d...", version)
            try:
                conn.execute("BEGIN")
                migrations[version](conn)
                conn.execute(
                    "INSERT INTO schema_version (version, applied_at)"
                    " VALUES (?, ?)",
                    (version, time.time()),
                )
                conn.commit()
                logger.info("Migration to version %d complete", version)
            except Exception:
                conn.rollback()
                logger.error(
                    "Migration to version %d failed, rolled back",
                    version, exc_info=True,
                )
                raise
```

- [ ] **Step 2: Run migration tests to verify they pass**

Run: `source .venv/bin/activate && python3 -m pytest tests/test_db.py -v -k "v1_to_v2"`
Expected: PASS (all 4 migration tests)

- [ ] **Step 3: Run all db tests to check nothing broke**

Run: `source .venv/bin/activate && python3 -m pytest tests/test_db.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add db.py
git commit -m "feat: add V1-to-V2 migration for track_downloads table"
```

---

## Chunk 2: Models Layer (models.py)

### Task 3: Write tests for new model functions

**Files:**
- Modify: `tests/test_models.py`

- [ ] **Step 1: Replace test_models.py with track_downloads tests**

The existing `temp_db` fixture calls `db.init_db()` which now creates V1 then migrates to V2. Replace the entire file with tests for the new functions.

```python
import time

import pytest

import db
import models


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr("db.DB_PATH", db_path)
    db.init_db()
    yield db_path
    db.close_db()


# --- Track Downloads ---


def test_add_track_download():
    models.add_track_download(
        album_id=1, album_title="Album1", artist_name="Artist1",
        track_title="Track1", track_number=1, success=True,
        error_message="", youtube_url="https://youtube.com/watch?v=abc",
        youtube_title="Artist1 - Track1", match_score=0.92,
        duration_seconds=240, album_path="/downloads/a",
        lidarr_album_path="/music/a", cover_url="http://cover.jpg",
    )
    tracks = models.get_track_downloads_for_album(1)
    assert len(tracks) == 1
    assert tracks[0]["track_title"] == "Track1"
    assert tracks[0]["youtube_url"] == "https://youtube.com/watch?v=abc"
    assert tracks[0]["success"] == 1


def test_get_track_downloads_for_album_ordered_newest_first():
    models.add_track_download(
        album_id=1, album_title="A", artist_name="A",
        track_title="T1", track_number=1, success=True,
        error_message="", youtube_url="", youtube_title="",
        match_score=0.0, duration_seconds=0,
        album_path="", lidarr_album_path="", cover_url="",
    )
    time.sleep(0.01)
    models.add_track_download(
        album_id=1, album_title="A", artist_name="A",
        track_title="T2", track_number=2, success=True,
        error_message="", youtube_url="", youtube_title="",
        match_score=0.0, duration_seconds=0,
        album_path="", lidarr_album_path="", cover_url="",
    )
    tracks = models.get_track_downloads_for_album(1)
    assert tracks[0]["track_title"] == "T2"


def test_get_album_history_grouped():
    models.add_track_download(
        album_id=1, album_title="Album1", artist_name="Artist1",
        track_title="T1", track_number=1, success=True,
        error_message="", youtube_url="", youtube_title="",
        match_score=0.0, duration_seconds=0,
        album_path="", lidarr_album_path="",
        cover_url="http://cover1.jpg",
    )
    models.add_track_download(
        album_id=1, album_title="Album1", artist_name="Artist1",
        track_title="T2", track_number=2, success=False,
        error_message="no match", youtube_url="", youtube_title="",
        match_score=0.0, duration_seconds=0,
        album_path="", lidarr_album_path="",
        cover_url="http://cover1.jpg",
    )
    result = models.get_album_history(page=1, per_page=50)
    assert result["total"] == 1  # 1 album group
    item = result["items"][0]
    assert item["album_id"] == 1
    assert item["success_count"] == 1
    assert item["fail_count"] == 1
    assert item["total_count"] == 2


def test_get_album_history_pagination():
    for i in range(3):
        models.add_track_download(
            album_id=i, album_title=f"Album{i}", artist_name="A",
            track_title="T1", track_number=1, success=True,
            error_message="", youtube_url="", youtube_title="",
            match_score=0.0, duration_seconds=0,
            album_path="", lidarr_album_path="", cover_url="",
        )
    result = models.get_album_history(page=1, per_page=2)
    assert result["total"] == 3
    assert result["pages"] == 2
    assert len(result["items"]) == 2


def test_get_failed_tracks_for_retry():
    models.add_track_download(
        album_id=1, album_title="A", artist_name="Ar",
        track_title="T1", track_number=1, success=False,
        error_message="no match", youtube_url="", youtube_title="",
        match_score=0.0, duration_seconds=0,
        album_path="/dl/a", lidarr_album_path="/music/a",
        cover_url="http://cover.jpg",
    )
    models.add_track_download(
        album_id=1, album_title="A", artist_name="Ar",
        track_title="T2", track_number=2, success=True,
        error_message="", youtube_url="http://yt/1", youtube_title="vid",
        match_score=0.9, duration_seconds=200,
        album_path="/dl/a", lidarr_album_path="/music/a",
        cover_url="http://cover.jpg",
    )
    result = models.get_failed_tracks_for_retry(1)
    assert result["album_id"] == 1
    assert result["album_path"] == "/dl/a"
    assert len(result["failed_tracks"]) == 1
    assert result["failed_tracks"][0]["title"] == "T1"


def test_get_failed_tracks_for_retry_latest_success_hides_old_failure():
    # First attempt fails
    models.add_track_download(
        album_id=1, album_title="A", artist_name="Ar",
        track_title="T1", track_number=1, success=False,
        error_message="no match", youtube_url="", youtube_title="",
        match_score=0.0, duration_seconds=0,
        album_path="/dl/a", lidarr_album_path="/music/a",
        cover_url="",
    )
    time.sleep(0.01)
    # Second attempt succeeds
    models.add_track_download(
        album_id=1, album_title="A", artist_name="Ar",
        track_title="T1", track_number=1, success=True,
        error_message="", youtube_url="http://yt/1", youtube_title="vid",
        match_score=0.9, duration_seconds=200,
        album_path="/dl/a", lidarr_album_path="/music/a",
        cover_url="",
    )
    result = models.get_failed_tracks_for_retry(1)
    assert len(result["failed_tracks"]) == 0


def test_get_history_count_today():
    models.add_track_download(
        album_id=1, album_title="A", artist_name="A",
        track_title="T1", track_number=1, success=True,
        error_message="", youtube_url="", youtube_title="",
        match_score=0.0, duration_seconds=0,
        album_path="", lidarr_album_path="", cover_url="",
    )
    models.add_track_download(
        album_id=1, album_title="A", artist_name="A",
        track_title="T2", track_number=2, success=True,
        error_message="", youtube_url="", youtube_title="",
        match_score=0.0, duration_seconds=0,
        album_path="", lidarr_album_path="", cover_url="",
    )
    models.add_track_download(
        album_id=2, album_title="B", artist_name="A",
        track_title="T1", track_number=1, success=False,
        error_message="fail", youtube_url="", youtube_title="",
        match_score=0.0, duration_seconds=0,
        album_path="", lidarr_album_path="", cover_url="",
    )
    # Counts distinct albums with at least one success today
    assert models.get_history_count_today() == 1


def test_get_history_album_ids_since():
    now = time.time()
    models.add_track_download(
        album_id=1, album_title="A", artist_name="A",
        track_title="T1", track_number=1, success=True,
        error_message="", youtube_url="", youtube_title="",
        match_score=0.0, duration_seconds=0,
        album_path="", lidarr_album_path="", cover_url="",
    )
    models.add_track_download(
        album_id=2, album_title="B", artist_name="A",
        track_title="T1", track_number=1, success=False,
        error_message="fail", youtube_url="", youtube_title="",
        match_score=0.0, duration_seconds=0,
        album_path="", lidarr_album_path="", cover_url="",
    )
    result = models.get_history_album_ids_since(now - 10)
    assert result == {1}


def test_clear_history():
    models.add_track_download(
        album_id=1, album_title="A", artist_name="A",
        track_title="T1", track_number=1, success=True,
        error_message="", youtube_url="", youtube_title="",
        match_score=0.0, duration_seconds=0,
        album_path="", lidarr_album_path="", cover_url="",
    )
    models.clear_history()
    result = models.get_album_history(page=1, per_page=50)
    assert result["total"] == 0


# --- Logs (updated -- no failed_tracks) ---


def test_add_log_no_failed_tracks():
    log_id = models.add_log(
        "download_success", 1, "Album", "Artist", details="ok"
    )
    assert log_id is not None
    result = models.get_logs(page=1, per_page=50)
    assert result["total"] == 1
    item = result["items"][0]
    assert item["type"] == "download_success"
    assert "failed_tracks" not in item


def test_add_log_track_level_id():
    log_id = models.add_log(
        "track_success", 1, "Album", "Artist",
        details="ok", track_number=3,
    )
    assert "_1_3" in log_id


def test_get_logs_filter_by_type():
    models.add_log("download_success", 1, "A", "A", details="ok")
    models.add_log("album_error", 2, "B", "B", details="fail")
    result = models.get_logs(page=1, per_page=50, log_type="album_error")
    assert result["total"] == 1
    assert result["items"][0]["type"] == "album_error"


def test_delete_log():
    models.add_log("download_success", 1, "A", "A")
    log_id = models.get_logs()["items"][0]["id"]
    assert models.delete_log(log_id) is True
    assert models.get_logs()["total"] == 0


def test_delete_log_not_found():
    assert models.delete_log("nonexistent") is False


def test_clear_logs():
    models.add_log("download_success", 1, "A", "A")
    models.clear_logs()
    assert models.get_logs()["total"] == 0


def test_get_logs_db_size():
    models.add_log("download_success", 1, "A", "A", details="some text")
    size = models.get_logs_db_size()
    assert size > 0


# --- Queue (unchanged) ---


def test_enqueue_and_get_queue():
    models.enqueue_album(10)
    models.enqueue_album(20)
    queue = models.get_queue()
    assert len(queue) == 2
    assert queue[0]["album_id"] == 10
    assert queue[1]["album_id"] == 20


def test_enqueue_duplicate_ignored():
    models.enqueue_album(10)
    models.enqueue_album(10)
    assert len(models.get_queue()) == 1


def test_dequeue_album():
    models.enqueue_album(10)
    models.enqueue_album(20)
    models.dequeue_album(10)
    queue = models.get_queue()
    assert len(queue) == 1
    assert queue[0]["album_id"] == 20


def test_set_queue_status():
    models.enqueue_album(10)
    models.set_queue_status(10, models.QUEUE_STATUS_DOWNLOADING)
    queue = models.get_queue()
    assert queue[0]["status"] == "downloading"


def test_set_queue_status_invalid():
    models.enqueue_album(10)
    with pytest.raises(ValueError):
        models.set_queue_status(10, "invalid_status")


def test_reset_downloading_to_queued():
    models.enqueue_album(10)
    models.set_queue_status(10, models.QUEUE_STATUS_DOWNLOADING)
    models.reset_downloading_to_queued()
    queue = models.get_queue()
    assert queue[0]["status"] == "queued"


def test_clear_queue():
    models.enqueue_album(10)
    models.clear_queue()
    assert len(models.get_queue()) == 0


def test_get_history_album_ids_since_empty():
    result = models.get_history_album_ids_since(time.time() - 10)
    assert result == set()


def test_get_history_album_ids_since_future_timestamp():
    models.add_track_download(
        album_id=1, album_title="A", artist_name="A",
        track_title="T1", track_number=1, success=True,
        error_message="", youtube_url="", youtube_title="",
        match_score=0.0, duration_seconds=0,
        album_path="", lidarr_album_path="", cover_url="",
    )
    result = models.get_history_album_ids_since(time.time() + 3600)
    assert result == set()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python3 -m pytest tests/test_models.py -v`
Expected: FAIL -- new model functions don't exist yet

- [ ] **Step 3: Commit**

```bash
git add tests/test_models.py
git commit -m "test: rewrite model tests for track_downloads schema"
```

### Task 4: Implement new model functions

**Files:**
- Modify: `models.py`

- [ ] **Step 1: Replace models.py content**

Replace the entire file. Keep `_paginate`, queue functions unchanged. Replace history section with track_downloads functions. Update log functions to drop `failed_tracks`.

```python
"""Data access layer for SQLite-backed persistence.

This is the ONLY module that writes SQL. All other modules call these
functions to read/write track downloads, logs, and the download queue.
"""

import logging
import math
import time
from datetime import datetime

import db

logger = logging.getLogger(__name__)

QUEUE_STATUS_QUEUED = "queued"
QUEUE_STATUS_DOWNLOADING = "downloading"
QUEUE_STATUSES = {QUEUE_STATUS_QUEUED, QUEUE_STATUS_DOWNLOADING}


def _paginate(query, count_query, params, page, per_page):
    """Run a paginated query and return a standard response dict."""
    conn = db.get_db()
    total = conn.execute(count_query, params).fetchone()[0]
    pages = max(1, math.ceil(total / per_page))
    page = max(1, min(page, pages))
    offset = (page - 1) * per_page
    rows = conn.execute(
        query + " LIMIT ? OFFSET ?", (*params, per_page, offset)
    ).fetchall()
    return {
        "items": [dict(row) for row in rows],
        "total": total,
        "page": page,
        "pages": pages,
        "per_page": per_page,
    }


# --- Track Downloads ---


def add_track_download(
    album_id, album_title, artist_name, track_title, track_number,
    success, error_message, youtube_url, youtube_title, match_score,
    duration_seconds, album_path, lidarr_album_path, cover_url,
):
    """Record a single track download attempt."""
    conn = db.get_db()
    conn.execute(
        """INSERT INTO track_downloads
           (album_id, album_title, artist_name, track_title,
            track_number, success, error_message, youtube_url,
            youtube_title, match_score, duration_seconds,
            album_path, lidarr_album_path, cover_url, timestamp)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            album_id, album_title, artist_name, track_title,
            track_number, int(success), error_message, youtube_url,
            youtube_title, match_score, duration_seconds,
            album_path, lidarr_album_path, cover_url, time.time(),
        ),
    )
    conn.commit()


def get_track_downloads_for_album(album_id):
    """Return all track download records for an album, newest first."""
    conn = db.get_db()
    rows = conn.execute(
        "SELECT * FROM track_downloads"
        " WHERE album_id = ? ORDER BY timestamp DESC",
        (album_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def get_album_history(page=1, per_page=50):
    """Return album-grouped download summaries, newest first."""
    query = """
        SELECT
            album_id,
            album_title,
            artist_name,
            cover_url,
            MAX(timestamp) as latest_timestamp,
            SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as success_count,
            SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as fail_count,
            COUNT(*) as total_count
        FROM track_downloads
        GROUP BY album_id, album_title, artist_name
        ORDER BY latest_timestamp DESC
    """
    count_query = """
        SELECT COUNT(DISTINCT album_id) FROM track_downloads
    """
    conn = db.get_db()
    total = conn.execute(count_query).fetchone()[0]
    pages = max(1, math.ceil(total / per_page))
    page = max(1, min(page, pages))
    offset = (page - 1) * per_page
    rows = conn.execute(
        query + " LIMIT ? OFFSET ?", (per_page, offset)
    ).fetchall()
    return {
        "items": [dict(row) for row in rows],
        "total": total,
        "page": page,
        "pages": pages,
        "per_page": per_page,
    }


def get_failed_tracks_for_retry(album_id):
    """Return failed tracks for retry UI.

    Returns tracks where the latest attempt for that track has
    success=0. Includes album context from the most recent row.
    """
    conn = db.get_db()
    context_row = conn.execute(
        "SELECT album_title, artist_name, cover_url,"
        " album_path, lidarr_album_path"
        " FROM track_downloads WHERE album_id = ?"
        " ORDER BY timestamp DESC LIMIT 1",
        (album_id,),
    ).fetchone()
    if context_row is None:
        return {
            "failed_tracks": [],
            "album_id": album_id,
            "album_title": "",
            "artist_name": "",
            "cover_url": "",
            "album_path": "",
            "lidarr_album_path": "",
        }
    # Get the latest attempt per track
    rows = conn.execute(
        """
        SELECT t1.track_title, t1.track_number, t1.error_message
        FROM track_downloads t1
        INNER JOIN (
            SELECT track_title, MAX(timestamp) as max_ts
            FROM track_downloads
            WHERE album_id = ?
            GROUP BY track_title
        ) t2 ON t1.track_title = t2.track_title
            AND t1.timestamp = t2.max_ts
        WHERE t1.album_id = ? AND t1.success = 0
        ORDER BY t1.track_number
        """,
        (album_id, album_id),
    ).fetchall()
    ctx = dict(context_row)
    return {
        "failed_tracks": [
            {
                "title": row["track_title"],
                "reason": row["error_message"],
                "track_num": row["track_number"],
            }
            for row in rows
        ],
        "album_id": album_id,
        "album_title": ctx["album_title"],
        "artist_name": ctx["artist_name"],
        "cover_url": ctx["cover_url"],
        "album_path": ctx["album_path"],
        "lidarr_album_path": ctx["lidarr_album_path"],
    }


def get_history_count_today():
    """Count distinct albums with successful tracks since midnight."""
    now = datetime.now()
    today_start = datetime(now.year, now.month, now.day).timestamp()
    conn = db.get_db()
    row = conn.execute(
        "SELECT COUNT(DISTINCT album_id) FROM track_downloads"
        " WHERE success = 1 AND timestamp >= ?",
        (today_start,),
    ).fetchone()
    return row[0]


def get_history_album_ids_since(since_timestamp):
    """Return set of album IDs with successful tracks since timestamp."""
    conn = db.get_db()
    rows = conn.execute(
        "SELECT DISTINCT album_id FROM track_downloads"
        " WHERE success = 1 AND timestamp >= ?",
        (since_timestamp,),
    ).fetchall()
    return {row[0] for row in rows}


def clear_history():
    """Delete all track download records."""
    conn = db.get_db()
    conn.execute("DELETE FROM track_downloads")
    conn.commit()


# --- Logs ---


def add_log(
    log_type, album_id, album_title, artist_name,
    details="", total_file_size=0, track_number=None,
):
    """Create a download log entry. Returns the generated log ID."""
    conn = db.get_db()
    ts = int(time.time() * 1000)
    if track_number is not None:
        log_id = f"{ts}_{album_id}_{track_number}"
    else:
        log_id = f"{ts}_{album_id}"
    conn.execute(
        """INSERT INTO download_logs
           (id, type, album_id, album_title, artist_name, timestamp,
            details, total_file_size)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            log_id, log_type, album_id, album_title, artist_name,
            time.time(), details, total_file_size,
        ),
    )
    conn.commit()
    return log_id


def get_logs(page=1, per_page=50, log_type=None):
    """Return paginated download logs, newest first."""
    if log_type:
        query = (
            "SELECT * FROM download_logs"
            " WHERE type = ? ORDER BY timestamp DESC"
        )
        count_query = (
            "SELECT COUNT(*) FROM download_logs WHERE type = ?"
        )
        params = (log_type,)
    else:
        query = "SELECT * FROM download_logs ORDER BY timestamp DESC"
        count_query = "SELECT COUNT(*) FROM download_logs"
        params = ()
    return _paginate(query, count_query, params, page, per_page)


def delete_log(log_id):
    """Delete a single log entry by ID. Returns True if deleted."""
    conn = db.get_db()
    cursor = conn.execute(
        "DELETE FROM download_logs WHERE id = ?", (log_id,)
    )
    conn.commit()
    return cursor.rowcount > 0


def clear_logs():
    """Delete all download log entries."""
    conn = db.get_db()
    conn.execute("DELETE FROM download_logs")
    conn.commit()


def get_logs_db_size():
    """Estimate the storage used by log text fields."""
    conn = db.get_db()
    row = conn.execute(
        "SELECT SUM(LENGTH(details)) FROM download_logs"
    ).fetchone()
    return row[0] or 0


# --- Queue ---


def enqueue_album(album_id):
    """Add an album to the download queue. Returns False if duplicate."""
    conn = db.get_db()
    existing = conn.execute(
        "SELECT id FROM download_queue WHERE album_id = ?", (album_id,)
    ).fetchone()
    if existing:
        return False
    max_pos = conn.execute(
        "SELECT COALESCE(MAX(position), 0) FROM download_queue"
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO download_queue (album_id, position, status)"
        " VALUES (?, ?, ?)",
        (album_id, max_pos + 1, QUEUE_STATUS_QUEUED),
    )
    conn.commit()
    return True


def dequeue_album(album_id):
    """Remove an album from the queue and reorder positions."""
    conn = db.get_db()
    conn.execute(
        "DELETE FROM download_queue WHERE album_id = ?", (album_id,)
    )
    conn.commit()
    _reorder_queue(conn)


def get_queue():
    """Return all queued albums ordered by position."""
    conn = db.get_db()
    rows = conn.execute(
        "SELECT * FROM download_queue ORDER BY position"
    ).fetchall()
    return [dict(row) for row in rows]


def get_queue_length():
    """Return the number of albums in the queue."""
    conn = db.get_db()
    return conn.execute(
        "SELECT COUNT(*) FROM download_queue"
    ).fetchone()[0]


def pop_next_from_queue():
    """Remove and return the next queued album_id, or None."""
    conn = db.get_db()
    row = conn.execute(
        "SELECT album_id FROM download_queue"
        " WHERE status = ? ORDER BY position LIMIT 1",
        (QUEUE_STATUS_QUEUED,),
    ).fetchone()
    if row is None:
        return None
    album_id = row[0]
    conn.execute(
        "DELETE FROM download_queue WHERE album_id = ?", (album_id,)
    )
    conn.commit()
    _reorder_queue(conn)
    return album_id


def set_queue_status(album_id, status):
    """Update the status of a queued album."""
    if status not in QUEUE_STATUSES:
        raise ValueError(
            f"Invalid queue status: {status}."
            f" Must be one of {QUEUE_STATUSES}"
        )
    conn = db.get_db()
    conn.execute(
        "UPDATE download_queue SET status = ? WHERE album_id = ?",
        (status, album_id),
    )
    conn.commit()


def reset_downloading_to_queued():
    """Reset any 'downloading' entries back to 'queued' on startup."""
    conn = db.get_db()
    conn.execute(
        "UPDATE download_queue SET status = ? WHERE status = ?",
        (QUEUE_STATUS_QUEUED, QUEUE_STATUS_DOWNLOADING),
    )
    conn.commit()


def clear_queue():
    """Delete all entries from the download queue."""
    conn = db.get_db()
    conn.execute("DELETE FROM download_queue")
    conn.commit()


def _reorder_queue(conn):
    """Renumber queue positions sequentially starting at 1."""
    rows = conn.execute(
        "SELECT id FROM download_queue ORDER BY position"
    ).fetchall()
    for i, row in enumerate(rows, 1):
        conn.execute(
            "UPDATE download_queue SET position = ? WHERE id = ?",
            (i, row[0]),
        )
    conn.commit()
```

- [ ] **Step 2: Run model tests**

Run: `source .venv/bin/activate && python3 -m pytest tests/test_models.py -v`
Expected: PASS

- [ ] **Step 3: Run all tests to check for regressions**

Run: `source .venv/bin/activate && python3 -m pytest tests/ -v`
Expected: Some route tests will fail (they reference old model functions) -- that's expected, fixed in Chunk 4.

- [ ] **Step 4: Commit**

```bash
git add models.py tests/test_models.py
git commit -m "feat: replace history/failed-tracks models with track_downloads"
```

---

## Chunk 3: Downloader Return Type + Processing Changes

### Task 5: Update downloader return type

**Files:**
- Modify: `downloader.py`
- Modify: `tests/test_downloader.py`

- [ ] **Step 1: Add test for new return type**

Add to `tests/test_downloader.py`:

```python
from unittest.mock import patch

from downloader import download_track_youtube


class TestDownloadTrackYoutubeReturnType:
    """download_track_youtube returns metadata dict, not True/string."""

    @patch("downloader.yt_dlp.YoutubeDL")
    def test_success_returns_metadata_dict(self, mock_ydl_class):
        mock_ydl = mock_ydl_class.return_value.__enter__.return_value
        mock_ydl.extract_info.return_value = {
            "entries": [{
                "url": "https://youtube.com/watch?v=abc",
                "title": "Artist - Track",
                "duration": 240,
                "channel": "ArtistVEVO",
                "view_count": 1000000,
            }],
        }
        mock_ydl.download.return_value = 0

        import tempfile
        import os
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "test")
            # Create the expected output file
            open(out + ".mp3", "w").close()
            result = download_track_youtube(
                "Artist Track official audio", out, "Track", 240000,
            )
        assert isinstance(result, dict)
        assert result["success"] is True
        assert "youtube_url" in result
        assert "youtube_title" in result
        assert "match_score" in result
        assert "duration_seconds" in result

    def test_no_candidates_returns_failure_dict(self):
        with patch("downloader.yt_dlp.YoutubeDL") as mock_ydl_class:
            mock_ydl = (
                mock_ydl_class.return_value.__enter__.return_value
            )
            mock_ydl.extract_info.return_value = {"entries": []}

            result = download_track_youtube(
                "Nonexistent Track", "/tmp/out", "Track", 240000,
            )
        assert isinstance(result, dict)
        assert result["success"] is False
        assert "error_message" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python3 -m pytest tests/test_downloader.py::TestDownloadTrackYoutubeReturnType -v`
Expected: FAIL

- [ ] **Step 3: Modify `download_track_youtube` to return metadata dict**

In `downloader.py`, change the return statements:

1. Line ~290 (`return f"Search failed: ..."`) becomes:
```python
return {
    "success": False,
    "error_message": f"Search failed: {str(e)[:120]}",
}
```

2. Lines ~296-299 (no candidates) becomes:
```python
return {
    "success": False,
    "error_message": (
        "No suitable YouTube match found"
        " (filtered by duration/forbidden words)"
    ),
}
```

3. Line ~340 (`return True`) becomes:
```python
return {
    "success": True,
    "youtube_url": candidate["url"],
    "youtube_title": candidate["title"],
    "match_score": round(candidate["score"], 4),
    "duration_seconds": int(candidate["duration"]),
}
```

4. Line ~367-368 (HTTP 403) becomes:
```python
return {
    "success": False,
    "error_message": (
        "HTTP 403 Forbidden"
        " - try providing/refreshing YouTube cookies"
    ),
}
```

5. Line ~370 (download failed) becomes:
```python
return {
    "success": False,
    "error_message": (
        f"Download failed after all attempts: {last_error_msg}"
    ),
}
```

- [ ] **Step 4: Run tests**

Run: `source .venv/bin/activate && python3 -m pytest tests/test_downloader.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add downloader.py tests/test_downloader.py
git commit -m "feat: download_track_youtube returns metadata dict"
```

### Task 6: Update processing.py

**Files:**
- Modify: `processing.py`
- Create: `tests/test_processing.py`

- [ ] **Step 1: Write processing tests**

Create `tests/test_processing.py`:

```python
"""Tests for processing module."""

import os
from unittest.mock import patch

import pytest

import db


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr("db.DB_PATH", db_path)
    db.init_db()
    yield db_path
    db.close_db()


class TestDownloadTracks:
    """_download_tracks calls add_track_download per track."""

    @patch("processing.download_track_youtube")
    @patch("processing.tag_mp3")
    @patch("processing.create_xml_metadata")
    @patch("processing.load_config", return_value={
        "xml_metadata_enabled": False,
    })
    def test_success_records_track_download(
        self, mock_config, mock_xml, mock_tag, mock_dl, tmp_path,
    ):
        import models
        from processing import _download_tracks, download_process

        album_path = str(tmp_path / "album")
        os.makedirs(album_path, exist_ok=True)

        track = {
            "title": "Test Track",
            "trackNumber": 1,
            "duration": 240000,
        }
        album = {"tracks": [track]}

        # Simulate successful download that creates the mp3 file
        def create_mp3(*args, **kwargs):
            temp_path = args[1]  # output_path
            open(temp_path + ".mp3", "w").close()
            return {
                "success": True,
                "youtube_url": "https://youtube.com/watch?v=abc",
                "youtube_title": "Artist - Test Track",
                "match_score": 0.92,
                "duration_seconds": 240,
            }
        mock_dl.side_effect = create_mp3

        download_process["stop"] = False
        download_process["progress"] = {
            "current": 0, "total": 0, "overall_percent": 0,
        }
        download_process["current_track_title"] = ""

        failed, size = _download_tracks(
            [track], album_path, "Artist", "Album",
            album, "mbid", "artist_mbid", None,
            album_id=42, cover_url="http://cover.jpg",
            lidarr_album_path="/music/a",
        )

        assert len(failed) == 0
        tracks = models.get_track_downloads_for_album(42)
        assert len(tracks) == 1
        assert tracks[0]["success"] == 1
        assert tracks[0]["youtube_url"] == (
            "https://youtube.com/watch?v=abc"
        )

    @patch("processing.download_track_youtube")
    @patch("processing.load_config", return_value={
        "xml_metadata_enabled": False,
    })
    def test_failure_records_track_download(
        self, mock_config, mock_dl, tmp_path,
    ):
        import models
        from processing import _download_tracks, download_process

        album_path = str(tmp_path / "album")
        os.makedirs(album_path, exist_ok=True)

        track = {
            "title": "Failed Track",
            "trackNumber": 1,
            "duration": 240000,
        }

        mock_dl.return_value = {
            "success": False,
            "error_message": "No suitable match",
        }

        download_process["stop"] = False
        download_process["progress"] = {
            "current": 0, "total": 0, "overall_percent": 0,
        }
        download_process["current_track_title"] = ""

        failed, size = _download_tracks(
            [track], album_path, "Artist", "Album",
            {"tracks": [track]}, "mbid", "artist_mbid", None,
            album_id=42, cover_url="",
            lidarr_album_path="",
        )

        assert len(failed) == 1
        tracks = models.get_track_downloads_for_album(42)
        assert len(tracks) == 1
        assert tracks[0]["success"] == 0
        assert tracks[0]["error_message"] == "No suitable match"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && python3 -m pytest tests/test_processing.py -v`
Expected: FAIL -- `_download_tracks` doesn't accept new params yet

- [ ] **Step 3: Update `_download_tracks` in processing.py**

Change the function signature to accept `album_id`, `cover_url`, and `lidarr_album_path`:

```python
def _download_tracks(
    tracks_to_download, album_path, artist_name, album_title,
    album, album_mbid, artist_mbid, cover_data,
    album_id, cover_url, lidarr_album_path,
):
```

In the loop body, replace the result checking. Change `download_result is True` to `download_result.get("success")`. Change `isinstance(download_result, str)` to `download_result.get("error_message", ...)`. Add `models.add_track_download()` calls after each success and failure.

After the success block (after `shutil.move(actual_file, final_file)`), add:
```python
            models.add_track_download(
                album_id=album_id, album_title=album_title,
                artist_name=artist_name, track_title=track_title,
                track_number=track_num, success=True,
                error_message="",
                youtube_url=download_result.get("youtube_url", ""),
                youtube_title=download_result.get("youtube_title", ""),
                match_score=download_result.get("match_score", 0.0),
                duration_seconds=download_result.get(
                    "duration_seconds", 0
                ),
                album_path=album_path,
                lidarr_album_path=lidarr_album_path,
                cover_url=cover_url,
            )
```

After the failure block (after `failed_tracks.append(...)`), add:
```python
            models.add_track_download(
                album_id=album_id, album_title=album_title,
                artist_name=artist_name, track_title=track_title,
                track_number=track_num, success=False,
                error_message=fail_reason,
                youtube_url="", youtube_title="",
                match_score=0.0, duration_seconds=0,
                album_path=album_path,
                lidarr_album_path=lidarr_album_path,
                cover_url=cover_url,
            )
```

- [ ] **Step 4: Update the call site in `process_album_download`**

Update the call to `_download_tracks` to pass the new params:

```python
        failed_tracks, total_downloaded_size = _download_tracks(
            tracks_to_download, album_path, artist_name, album_title,
            album, album_mbid, artist_mbid, cover_data,
            album_id=album_id,
            cover_url=download_process.get("cover_url", ""),
            lidarr_album_path=lidarr_album_path,
        )
```

- [ ] **Step 5: Remove `save_failed_tracks` and `add_history_entry` from `finally` block**

Replace the `finally` block in `process_album_download`. Remove calls to `models.save_failed_tracks()`, `models.clear_failed_tracks()`, and `models.add_history_entry()`:

```python
    finally:
        with queue_lock:
            download_process["active"] = False
            download_process["progress"] = {}
            download_process["album_id"] = None
            download_process["album_title"] = ""
            download_process["artist_name"] = ""
            download_process["current_track_title"] = ""
            download_process["cover_url"] = ""
```

- [ ] **Step 6: Remove `failed_tracks=` from all `add_log` calls in processing.py**

Remove the `failed_tracks=...` keyword argument from every `models.add_log()` call in processing.py. There are calls in `process_album_download`, `_handle_post_download`, and `_log_import_result`.

- [ ] **Step 7: Run processing tests**

Run: `source .venv/bin/activate && python3 -m pytest tests/test_processing.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add processing.py tests/test_processing.py
git commit -m "feat: record per-track downloads inline in _download_tracks"
```

---

## Chunk 4: Routes + API Changes (app.py)

### Task 7: Update route tests

**Files:**
- Modify: `tests/test_routes.py`

- [ ] **Step 1: Update route tests for new data shapes**

Replace `TestHistoryRoutes`, `TestFailedTracksRoute`, `TestStatsRoute`, and `TestLogsRoutes` classes. Add `TestTracksEndpoint`. Keep all other test classes unchanged.

```python
class TestHistoryRoutes:
    def test_get_history_empty(self, client):
        resp = client.get("/api/download/history")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["page"] == 1

    def test_get_history_grouped(self, client):
        import models

        models.add_track_download(
            1, "Album A", "Artist A", "T1", 1, True, "",
            "http://yt/1", "vid1", 0.9, 200, "", "", "",
        )
        models.add_track_download(
            1, "Album A", "Artist A", "T2", 2, False, "fail",
            "", "", 0.0, 0, "", "", "",
        )
        resp = client.get("/api/download/history")
        data = resp.get_json()
        assert data["total"] == 1  # 1 album
        item = data["items"][0]
        assert item["success_count"] == 1
        assert item["fail_count"] == 1

    def test_get_history_pagination(self, client):
        import models

        for i in range(5):
            models.add_track_download(
                i, f"Album {i}", "Artist", "T1", 1, True, "",
                "", "", 0.0, 0, "", "", "",
            )
        resp = client.get("/api/download/history?page=1&per_page=2")
        data = resp.get_json()
        assert data["total"] == 5
        assert len(data["items"]) == 2
        assert data["pages"] == 3

    def test_clear_history(self, client):
        import models

        models.add_track_download(
            1, "A", "A", "T1", 1, True, "",
            "", "", 0.0, 0, "", "", "",
        )
        resp = client.post("/api/download/history/clear")
        assert resp.status_code == 200
        resp2 = client.get("/api/download/history")
        assert resp2.get_json()["total"] == 0


class TestTracksEndpoint:
    def test_get_tracks_for_album(self, client):
        import models

        models.add_track_download(
            42, "Album", "Artist", "Track1", 1, True, "",
            "http://yt/1", "vid1", 0.92, 240, "/dl", "/music", "",
        )
        models.add_track_download(
            42, "Album", "Artist", "Track2", 2, False, "no match",
            "", "", 0.0, 0, "/dl", "/music", "",
        )
        resp = client.get("/api/download/history/42/tracks")
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data) == 2

    def test_get_tracks_empty(self, client):
        resp = client.get("/api/download/history/999/tracks")
        assert resp.status_code == 200
        assert resp.get_json() == []


class TestLogsRoutes:
    def test_get_logs_empty(self, client):
        resp = client.get("/api/logs")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_get_logs_no_failed_tracks_field(self, client):
        import models

        models.add_log("download_success", 1, "A", "A", "OK")
        resp = client.get("/api/logs")
        item = resp.get_json()["items"][0]
        assert "failed_tracks" not in item

    def test_get_logs_pagination(self, client):
        import models

        for i in range(5):
            models.add_log(
                "download_success", i, f"Album {i}", "Artist", "OK"
            )
        resp = client.get("/api/logs?page=1&per_page=2")
        data = resp.get_json()
        assert data["total"] == 5
        assert len(data["items"]) == 2

    def test_dismiss_log(self, client):
        import models

        log_id = models.add_log(
            "download_success", 1, "A", "A", "OK"
        )
        resp = client.delete(f"/api/logs/{log_id}/dismiss")
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True

    def test_dismiss_nonexistent_log(self, client):
        resp = client.delete("/api/logs/nonexistent_123/dismiss")
        assert resp.status_code == 404

    def test_clear_logs(self, client):
        import models

        models.add_log("download_success", 1, "A", "A", "OK")
        resp = client.post("/api/logs/clear")
        assert resp.status_code == 200

    def test_logs_size(self, client):
        resp = client.get("/api/logs/size")
        data = resp.get_json()
        assert "size" in data
        assert "formatted" in data


class TestFailedTracksRoute:
    def test_get_failed_tracks_empty(self, client):
        resp = client.get("/api/download/failed")
        data = resp.get_json()
        assert data["failed_tracks"] == []

    def test_get_failed_tracks_with_data(self, client):
        import models

        models.add_track_download(
            42, "Test Album", "Test Artist", "Track 1", 1,
            False, "Not found", "", "", 0.0, 0,
            "/tmp/downloads/test", "/tmp/music/test",
            "http://example.com/cover.jpg",
        )
        models.add_track_download(
            42, "Test Album", "Test Artist", "Track 2", 2,
            True, "", "http://yt/1", "vid", 0.9, 200,
            "/tmp/downloads/test", "/tmp/music/test",
            "http://example.com/cover.jpg",
        )
        resp = client.get("/api/download/failed")
        data = resp.get_json()
        assert len(data["failed_tracks"]) == 1
        assert data["album_id"] == 42


class TestStatsRoute:
    def test_stats_empty(self, client):
        resp = client.get("/api/stats")
        data = resp.get_json()
        assert data["downloaded_today"] == 0
        assert data["in_queue"] == 0

    def test_stats_with_downloads(self, client):
        import models

        models.add_track_download(
            1, "A", "A", "T1", 1, True, "",
            "", "", 0.0, 0, "", "", "",
        )
        resp = client.get("/api/stats")
        data = resp.get_json()
        assert data["downloaded_today"] == 1

    def test_stats_with_queue(self, client):
        import models

        models.enqueue_album(100)
        models.enqueue_album(200)
        resp = client.get("/api/stats")
        data = resp.get_json()
        assert data["in_queue"] == 2
```

- [ ] **Step 2: Run to verify they fail**

Run: `source .venv/bin/activate && python3 -m pytest tests/test_routes.py -v -k "History or Tracks or Logs or Failed or Stats"`
Expected: FAIL -- route changes not yet made

- [ ] **Step 3: Commit test updates**

```bash
git add tests/test_routes.py
git commit -m "test: update route tests for track-level history"
```

### Task 8: Update app.py routes

**Files:**
- Modify: `app.py`

- [ ] **Step 1: Update history route to use `get_album_history`**

Replace `api_download_history`:

```python
@app.route("/api/download/history")
def api_download_history():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    return jsonify(models.get_album_history(page, per_page))
```

- [ ] **Step 2: Add tracks endpoint**

Add after the history routes:

```python
@app.route("/api/download/history/<int:album_id>/tracks")
def api_album_tracks(album_id):
    return jsonify(models.get_track_downloads_for_album(album_id))
```

- [ ] **Step 3: Update failed tracks route**

Replace `api_download_failed` to infer album from most recent download:

```python
@app.route("/api/download/failed")
def api_download_failed():
    conn = db.get_db()
    row = conn.execute(
        "SELECT DISTINCT album_id FROM track_downloads"
        " ORDER BY timestamp DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return jsonify({
            "failed_tracks": [],
            "album_id": None,
            "album_title": "",
            "artist_name": "",
            "cover_url": "",
            "album_path": "",
            "lidarr_album_path": "",
        })
    return jsonify(models.get_failed_tracks_for_retry(row[0]))
```

- [ ] **Step 4: Update manual download route**

In `api_download_manual()`:
- Replace `failed_ctx = models.get_failed_tracks_context()` with inferring album_id then calling `models.get_failed_tracks_for_retry(album_id_ctx)`
- Replace `models.remove_failed_track(track_title)` with `models.add_track_download(...)` (new success row)
- Remove `models.add_history_entry(...)` call
- Remove `failed_tracks=[]` from `models.add_log(...)` call

In `_execute_manual_download()`, replace `models.remove_failed_track(track_title)` with:

```python
        models.add_track_download(
            album_id=album_id_ctx, album_title=album_title,
            artist_name=artist_name, track_title=track_title,
            track_number=int(track_num), success=True,
            error_message="",
            youtube_url=youtube_url,
            youtube_title="Manual download",
            match_score=1.0,
            duration_seconds=0,
            album_path=failed_ctx.get("album_path", ""),
            lidarr_album_path=failed_ctx.get("lidarr_album_path", ""),
            cover_url=failed_ctx.get("cover_url", ""),
        )
```

Remove the `models.add_history_entry(...)` call and the `failed_tracks=[]` from `models.add_log(...)`.

- [ ] **Step 5: Run route tests**

Run: `source .venv/bin/activate && python3 -m pytest tests/test_routes.py -v`
Expected: PASS

- [ ] **Step 6: Run all tests**

Run: `source .venv/bin/activate && python3 -m pytest tests/ -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app.py
git commit -m "feat: update routes for track-level history API"
```

---

## Chunk 5: UI Changes (downloads.html)

### Task 9: Update downloads page template

**Files:**
- Modify: `templates/downloads.html`

- [ ] **Step 1: Add CSS for expandable track rows**

Add these styles inside the `<style>` block, after the `.history-manual-label` block (around line 594). Remove `.history-item.history-manual` and `.status-icon.manual` and `.history-manual-label` styles since the `manual` flag is dropped.

```css
.history-album-row {
    cursor: pointer;
    user-select: none;
}

.history-expand-icon {
    color: var(--text-dim);
    font-size: 0.75rem;
    transition: transform 0.2s ease;
    width: 20px;
    text-align: center;
    flex-shrink: 0;
}

.history-expand-icon.expanded {
    transform: rotate(90deg);
    color: var(--primary);
}

.history-track-badge {
    padding: 0.15rem 0.5rem;
    border-radius: 4px;
    font-size: 0.75rem;
    font-weight: 600;
    white-space: nowrap;
}

.history-track-badge.badge-success {
    background: rgba(16, 185, 129, 0.15);
    color: var(--primary);
}

.history-track-badge.badge-partial {
    background: rgba(245, 158, 11, 0.15);
    color: #f59e0b;
}

.history-track-badge.badge-error {
    background: rgba(239, 68, 68, 0.15);
    color: var(--danger);
}

.track-detail-grid {
    background: var(--bg);
    border: 1px solid var(--border);
    border-top: none;
    border-radius: 0 0 12px 12px;
    padding: 0.5rem;
    margin-bottom: 0.75rem;
    margin-top: -0.75rem;
}

.track-detail-header,
.track-detail-row {
    display: grid;
    grid-template-columns: 40px 1fr 1fr 65px 55px 130px;
    padding: 0.4rem 0.75rem;
    align-items: center;
    font-size: 0.8rem;
}

.track-detail-header {
    color: var(--text-dim);
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    border-bottom: 1px solid var(--border);
}

.track-detail-row {
    border-bottom: 1px solid rgba(255, 255, 255, 0.03);
}

.track-detail-row.track-failed {
    background: rgba(239, 68, 68, 0.05);
}

.track-detail-row a {
    color: #3b82f6;
    text-decoration: none;
    font-size: 0.75rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.track-detail-row a:hover {
    text-decoration: underline;
}

.track-attempts {
    color: var(--text-dim);
    font-size: 0.7rem;
    margin-left: 0.3rem;
}

@media (max-width: 768px) {
    .track-detail-header,
    .track-detail-row {
        grid-template-columns: 30px 1fr 60px;
    }
    .track-detail-header > :nth-child(3),
    .track-detail-header > :nth-child(4),
    .track-detail-header > :nth-child(6),
    .track-detail-row > :nth-child(3),
    .track-detail-row > :nth-child(4),
    .track-detail-row > :nth-child(6) {
        display: none;
    }
}
```

- [ ] **Step 2: Replace `renderHistoryItem` JavaScript function**

Replace the entire `renderHistoryItem` function and add `getAlbumStatus` and `toggleTracks` functions. All user values pass through `escapeHtml()` (creates DOM text nodes) and `sanitizeUrl()` (validates protocol) -- matching existing XSS protection patterns in the template.

```javascript
function getAlbumStatus(item) {
    if (item.fail_count === 0) return 'success';
    if (item.success_count === 0) return 'error';
    return 'partial';
}

function renderHistoryItem(item) {
    const status = getAlbumStatus(item);
    const iconMap = {
        success: 'fa-solid fa-check',
        partial: 'fa-solid fa-triangle-exclamation',
        error: 'fa-solid fa-xmark',
    };
    const badgeClass = 'badge-' + status;
    const albumId = item.album_id;

    return '<div class="history-item history-' + status + ' history-album-row" onclick="toggleTracks(this, ' + albumId + ')">'
        + '<span class="history-expand-icon" id="expand-icon-' + albumId + '"><i class="fa-solid fa-chevron-right"></i></span>'
        + '<div class="status-icon ' + status + '"><i class="' + iconMap[status] + '"></i></div>'
        + '<div class="history-info">'
        + '<div class="history-title">' + escapeHtml(item.album_title || 'Unknown') + '</div>'
        + '<div class="history-meta">' + escapeHtml(item.artist_name || 'Unknown Artist') + ' \u2022 ' + new Date(item.latest_timestamp * 1000).toLocaleString() + '</div>'
        + '</div>'
        + '<span class="history-track-badge ' + badgeClass + '">' + item.success_count + '/' + item.total_count + ' tracks</span>'
        + '</div>'
        + '<div class="track-detail-grid" id="tracks-' + albumId + '" style="display:none;"></div>';
}

async function toggleTracks(row, albumId) {
    const grid = document.getElementById('tracks-' + albumId);
    const icon = document.getElementById('expand-icon-' + albumId);

    if (grid.style.display !== 'none') {
        grid.style.display = 'none';
        icon.classList.remove('expanded');
        return;
    }

    icon.classList.add('expanded');
    grid.textContent = '';
    const loading = document.createElement('div');
    loading.style.cssText = 'padding:1rem;color:var(--text-dim);text-align:center;';
    loading.textContent = 'Loading...';
    grid.appendChild(loading);
    grid.style.display = 'block';

    try {
        const resp = await fetch('/api/download/history/' + albumId + '/tracks');
        const tracks = await resp.json();
        if (tracks.length === 0) {
            grid.textContent = '';
            const empty = document.createElement('div');
            empty.style.cssText = 'padding:1rem;color:var(--text-dim);text-align:center;';
            empty.textContent = 'No track data';
            grid.appendChild(empty);
            return;
        }

        // Group by track title to count attempts, show latest
        const byTrack = {};
        for (const t of tracks) {
            const key = t.track_title;
            if (!byTrack[key]) byTrack[key] = [];
            byTrack[key].push(t);
        }

        // Sort by track_number of latest attempt
        const sorted = Object.values(byTrack).map(function(attempts) {
            attempts.sort(function(a, b) { return b.timestamp - a.timestamp; });
            return { latest: attempts[0], attempts: attempts.length };
        });
        sorted.sort(function(a, b) { return a.latest.track_number - b.latest.track_number; });

        // Build DOM elements safely
        const container = document.createDocumentFragment();

        // Header
        const header = document.createElement('div');
        header.className = 'track-detail-header';
        ['#', 'Track', 'YouTube Source', 'Score', 'Dur.', 'Downloaded'].forEach(function(text) {
            const cell = document.createElement('div');
            cell.textContent = text;
            header.appendChild(cell);
        });
        container.appendChild(header);

        // Rows
        sorted.forEach(function(item) {
            var t = item.latest;
            var attempts = item.attempts;
            var isFailed = !t.success;
            var row = document.createElement('div');
            row.className = isFailed ? 'track-detail-row track-failed' : 'track-detail-row';

            // Track number
            var numCell = document.createElement('div');
            numCell.style.color = 'var(--text-dim)';
            numCell.textContent = String(t.track_number).padStart(2, '0');
            row.appendChild(numCell);

            // Track title + attempts
            var titleCell = document.createElement('div');
            titleCell.style.color = isFailed ? 'var(--danger)' : 'var(--text)';
            titleCell.textContent = t.track_title;
            if (attempts > 1) {
                var badge = document.createElement('span');
                badge.className = 'track-attempts';
                badge.title = attempts + ' download attempts';
                badge.textContent = '(' + attempts + ' attempts)';
                titleCell.appendChild(badge);
            }
            row.appendChild(titleCell);

            // YouTube source
            var ytCell = document.createElement('div');
            if (isFailed) {
                ytCell.style.cssText = 'color:var(--danger);font-size:0.75rem;';
                ytCell.textContent = t.error_message || 'Failed';
            } else if (t.youtube_url) {
                var safeUrl = sanitizeUrl(t.youtube_url);
                if (safeUrl) {
                    var link = document.createElement('a');
                    link.href = safeUrl;
                    link.target = '_blank';
                    link.rel = 'noopener';
                    link.title = t.youtube_title || t.youtube_url;
                    link.textContent = t.youtube_title || t.youtube_url;
                    ytCell.appendChild(link);
                } else {
                    ytCell.style.color = 'var(--text-dim)';
                    ytCell.textContent = t.youtube_title || '\u2014';
                }
            } else {
                ytCell.style.color = 'var(--text-dim)';
                ytCell.textContent = '\u2014';
            }
            row.appendChild(ytCell);

            // Score
            var scoreCell = document.createElement('div');
            if (isFailed) {
                scoreCell.style.color = 'var(--text-dim)';
                scoreCell.textContent = '\u2014';
            } else {
                scoreCell.style.color = '#6ee7b7';
                scoreCell.textContent = t.match_score ? t.match_score.toFixed(2) : '\u2014';
            }
            row.appendChild(scoreCell);

            // Duration
            var durCell = document.createElement('div');
            durCell.style.color = 'var(--text-dim)';
            if (isFailed || !t.duration_seconds) {
                durCell.textContent = '\u2014';
            } else {
                durCell.textContent = Math.floor(t.duration_seconds / 60) + ':' + String(t.duration_seconds % 60).padStart(2, '0');
            }
            row.appendChild(durCell);

            // Timestamp
            var timeCell = document.createElement('div');
            timeCell.style.cssText = 'color:var(--text-dim);font-size:0.75rem;';
            timeCell.textContent = new Date(t.timestamp * 1000).toLocaleString([], {month:'short',day:'numeric',hour:'numeric',minute:'2-digit'});
            row.appendChild(timeCell);

            container.appendChild(row);
        });

        grid.textContent = '';
        grid.appendChild(container);
    } catch (e) {
        grid.textContent = '';
        var errDiv = document.createElement('div');
        errDiv.style.cssText = 'padding:1rem;color:var(--danger);text-align:center;';
        errDiv.textContent = 'Failed to load tracks';
        grid.appendChild(errDiv);
    }
}
```

- [ ] **Step 3: Run template route tests**

Run: `source .venv/bin/activate && python3 -m pytest tests/test_routes.py::TestTemplateRoutes -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add templates/downloads.html
git commit -m "feat: expandable track rows in downloads history UI"
```

---

## Chunk 6: Final Integration + Manual Testing Updates

### Task 10: Update TESTING.md

**Files:**
- Modify: `TESTING.md`

- [ ] **Step 1: Update TESTING.md with new test items**

Add to the API Smoke Tests section:
```markdown
- [ ] `GET /api/download/history` -- returns paginated response with grouped albums (each item has `success_count`, `fail_count`, `total_count`)
- [ ] `GET /api/download/history/<album_id>/tracks` -- returns track-level download records
- [ ] `GET /api/download/failed` -- returns failed tracks inferred from most recent download batch
```

Add to the UI Interaction Tests section:
```markdown
- [ ] **Downloads page**: History shows album rows with color-coded track count badges
- [ ] **Downloads page**: Click album row to expand -- shows track detail grid
- [ ] **Downloads page**: Expanded tracks show YouTube links, match scores, durations
- [ ] **Downloads page**: Failed tracks shown with red background and error message
- [ ] **Downloads page**: Multiple attempt indicator shows "(N attempts)" on re-downloaded tracks
```

- [ ] **Step 2: Commit**

```bash
git add TESTING.md
git commit -m "docs: update manual testing checklist for track-level history"
```

### Task 11: Run full test suite and verify

- [ ] **Step 1: Run all tests**

Run: `source .venv/bin/activate && python3 -m pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 2: Run linter**

Run: `source .venv/bin/activate && ruff check .`
Expected: No errors

- [ ] **Step 3: Build and run Docker for manual smoke test**

Run: `docker compose up -d --build`
Expected: Container starts, app loads at http://localhost:5000

- [ ] **Step 4: Verify downloads page loads**

Navigate to http://localhost:5000/downloads -- should show empty history with no errors.

- [ ] **Step 5: Stop Docker**

Run: `docker compose down`

- [ ] **Step 6: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix: integration fixes for track-level history"
```
