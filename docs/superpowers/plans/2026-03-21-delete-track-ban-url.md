# Delete Track + Ban URL Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow users to delete downloaded tracks from disk and optionally ban the YouTube URL so it is skipped on future re-downloads of that track.

**Architecture:** New `banned_urls` table + `deleted` column on `track_downloads` (V3->V4 migration). File deletion logic in a route handler. Banned URL filtering injected into the downloader's search loop via a `banned_urls` parameter. Logs page extended to show/unban entries from the new table.

**Tech Stack:** Python/Flask, SQLite, vanilla JS (existing UI patterns)

**Spec:** `docs/superpowers/specs/2026-03-21-delete-track-ban-url-design.md`

---

### Task 1: Database Migration V3 to V4

**Files:**
- Modify: `db.py:12` (SCHEMA_VERSION), `db.py:248-275` (_run_migrations)
- Test: `tests/test_db.py`

- [ ] **Step 1: Write failing test for V4 migration**

In `tests/test_db.py`, add:

```python
def test_migration_v3_to_v4_creates_banned_urls(temp_db):
    init_db()
    conn = sqlite3.connect(temp_db)
    tables = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    ]
    assert "banned_urls" in tables
    cols = [
        row[1]
        for row in conn.execute("PRAGMA table_info(banned_urls)")
    ]
    assert "youtube_url" in cols
    assert "album_id" in cols
    assert "track_title" in cols
    assert "banned_at" in cols
    conn.close()


def test_migration_v3_to_v4_adds_deleted_column(temp_db):
    init_db()
    conn = sqlite3.connect(temp_db)
    cols = [
        row[1]
        for row in conn.execute("PRAGMA table_info(track_downloads)")
    ]
    assert "deleted" in cols
    conn.close()


def test_schema_version_is_4(temp_db):
    init_db()
    conn = sqlite3.connect(temp_db)
    row = conn.execute(
        "SELECT version FROM schema_version"
        " ORDER BY version DESC LIMIT 1"
    ).fetchone()
    conn.close()
    assert row[0] == 4
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python3 -m pytest tests/test_db.py::test_migration_v3_to_v4_creates_banned_urls tests/test_db.py::test_migration_v3_to_v4_adds_deleted_column tests/test_db.py::test_schema_version_is_4 -v`

Expected: FAIL — `banned_urls` table does not exist, `deleted` column missing, version is 3

- [ ] **Step 3: Implement migration**

In `db.py`:

1. Change line 12: `SCHEMA_VERSION = 4`

2. Add migration function after `_migrate_v2_to_v3` (after line 245):

```python
def _migrate_v3_to_v4(conn):
    """Add banned_urls table and deleted column to track_downloads."""
    conn.execute("""
        CREATE TABLE banned_urls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            youtube_url TEXT NOT NULL,
            youtube_title TEXT,
            album_id INTEGER NOT NULL,
            album_title TEXT,
            artist_name TEXT,
            track_title TEXT NOT NULL,
            track_number INTEGER,
            banned_at REAL NOT NULL,
            UNIQUE(youtube_url, album_id, track_title)
        )
    """)
    conn.execute(
        "CREATE INDEX idx_banned_urls_lookup"
        " ON banned_urls(album_id, track_title)"
    )
    conn.execute(
        "CREATE INDEX idx_banned_urls_timestamp"
        " ON banned_urls(banned_at)"
    )
    conn.execute(
        "ALTER TABLE track_downloads"
        " ADD COLUMN deleted INTEGER DEFAULT 0"
    )
```

3. Register in `_run_migrations` dict (line 250-253):

```python
    migrations = {
        2: _migrate_v1_to_v2,
        3: _migrate_v2_to_v3,
        4: _migrate_v3_to_v4,
    }
```

- [ ] **Step 4: Fix existing test assertions**

Update `test_init_db_sets_schema_version` to expect version 4:
```python
assert row[0] == 4
```

Update `test_init_db_idempotent` to expect 4 version rows:
```python
# V1 insert + V2 migration + V3 migration + V4 migration = 4 rows
assert rows[0] == 4
```

- [ ] **Step 5: Run all db tests to verify they pass**

Run: `source .venv/bin/activate && python3 -m pytest tests/test_db.py -v`

Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add db.py tests/test_db.py
git commit -m "feat: add V4 migration for banned_urls table and deleted column"
```

---

### Task 2: Model Functions for Banned URLs

**Files:**
- Modify: `models.py` (add functions after line 221, before `# --- Logs ---`)
- Test: `tests/test_models.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_models.py`:

```python
# --- Banned URLs ---


def test_add_banned_url():
    models.add_banned_url(
        youtube_url="https://youtube.com/watch?v=abc",
        youtube_title="Wrong Video",
        album_id=1,
        album_title="Album1",
        artist_name="Artist1",
        track_title="Track1",
        track_number=1,
    )
    result = models.get_banned_urls(page=1, per_page=50)
    assert result["total"] == 1
    item = result["items"][0]
    assert item["youtube_url"] == "https://youtube.com/watch?v=abc"
    assert item["track_title"] == "Track1"
    assert item["album_id"] == 1


def test_add_banned_url_duplicate_ignored():
    models.add_banned_url(
        youtube_url="https://youtube.com/watch?v=abc",
        youtube_title="Wrong Video",
        album_id=1, album_title="A", artist_name="A",
        track_title="Track1", track_number=1,
    )
    models.add_banned_url(
        youtube_url="https://youtube.com/watch?v=abc",
        youtube_title="Wrong Video",
        album_id=1, album_title="A", artist_name="A",
        track_title="Track1", track_number=1,
    )
    result = models.get_banned_urls(page=1, per_page=50)
    assert result["total"] == 1


def test_get_banned_urls_for_track():
    models.add_banned_url(
        youtube_url="https://youtube.com/watch?v=abc",
        youtube_title="V1", album_id=1, album_title="A",
        artist_name="A", track_title="Track1", track_number=1,
    )
    models.add_banned_url(
        youtube_url="https://youtube.com/watch?v=def",
        youtube_title="V2", album_id=1, album_title="A",
        artist_name="A", track_title="Track1", track_number=1,
    )
    # Different track - should not appear
    models.add_banned_url(
        youtube_url="https://youtube.com/watch?v=abc",
        youtube_title="V1", album_id=1, album_title="A",
        artist_name="A", track_title="Track2", track_number=2,
    )
    banned = models.get_banned_urls_for_track(1, "Track1")
    assert banned == {
        "https://youtube.com/watch?v=abc",
        "https://youtube.com/watch?v=def",
    }


def test_remove_banned_url():
    models.add_banned_url(
        youtube_url="https://youtube.com/watch?v=abc",
        youtube_title="V1", album_id=1, album_title="A",
        artist_name="A", track_title="Track1", track_number=1,
    )
    result = models.get_banned_urls(page=1, per_page=50)
    ban_id = result["items"][0]["id"]
    assert models.remove_banned_url(ban_id) is True
    assert models.get_banned_urls(page=1, per_page=50)["total"] == 0


def test_remove_banned_url_nonexistent():
    assert models.remove_banned_url(9999) is False


def test_mark_track_deleted():
    models.add_track_download(
        album_id=1, album_title="A", artist_name="A",
        track_title="T1", track_number=1, success=True,
        error_message="", youtube_url="https://yt/abc",
        youtube_title="vid", match_score=0.9,
        duration_seconds=200, album_path="/dl/a",
        lidarr_album_path="/music/a", cover_url="",
    )
    tracks = models.get_track_downloads_for_album(1)
    track_id = tracks[0]["id"]
    track_data = models.mark_track_deleted(track_id)
    assert track_data is not None
    assert track_data["album_path"] == "/dl/a"
    assert track_data["track_title"] == "T1"
    # Verify it's now marked deleted
    tracks = models.get_track_downloads_for_album(1)
    assert tracks[0]["deleted"] == 1


def test_mark_track_deleted_nonexistent():
    assert models.mark_track_deleted(9999) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python3 -m pytest tests/test_models.py -k "banned_url or mark_track_deleted" -v`

Expected: FAIL — functions don't exist

- [ ] **Step 3: Implement model functions**

Add to `models.py` after `clear_history()` (line 221), before the `# --- Logs ---` section:

```python
# --- Banned URLs ---


def add_banned_url(
    youtube_url, youtube_title, album_id, album_title,
    artist_name, track_title, track_number,
):
    """Ban a YouTube URL for a specific track. Ignores duplicates."""
    conn = db.get_db()
    conn.execute(
        """INSERT OR IGNORE INTO banned_urls
           (youtube_url, youtube_title, album_id, album_title,
            artist_name, track_title, track_number, banned_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            youtube_url, youtube_title, album_id, album_title,
            artist_name, track_title, track_number, time.time(),
        ),
    )
    conn.commit()


def get_banned_urls(page=1, per_page=50):
    """Return paginated banned URLs, newest first."""
    query = "SELECT * FROM banned_urls ORDER BY banned_at DESC"
    count_query = "SELECT COUNT(*) FROM banned_urls"
    return _paginate(query, count_query, (), page, per_page)


def get_banned_urls_for_track(album_id, track_title):
    """Return set of banned YouTube URLs for a specific track."""
    conn = db.get_db()
    rows = conn.execute(
        "SELECT youtube_url FROM banned_urls"
        " WHERE album_id = ? AND track_title = ?",
        (album_id, track_title),
    ).fetchall()
    return {row[0] for row in rows}


def remove_banned_url(ban_id):
    """Delete a ban by ID. Returns True if deleted."""
    conn = db.get_db()
    cursor = conn.execute(
        "DELETE FROM banned_urls WHERE id = ?", (ban_id,)
    )
    conn.commit()
    return cursor.rowcount > 0


def mark_track_deleted(track_id):
    """Set deleted=1 on a track download. Returns the row dict or None."""
    conn = db.get_db()
    row = conn.execute(
        "SELECT * FROM track_downloads WHERE id = ?",
        (track_id,),
    ).fetchone()
    if row is None:
        return None
    conn.execute(
        "UPDATE track_downloads SET deleted = 1 WHERE id = ?",
        (track_id,),
    )
    conn.commit()
    return dict(row)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && python3 -m pytest tests/test_models.py -k "banned_url or mark_track_deleted" -v`

Expected: All PASS

- [ ] **Step 5: Run full model test suite**

Run: `source .venv/bin/activate && python3 -m pytest tests/test_models.py -v`

Expected: All PASS (existing tests unaffected)

- [ ] **Step 6: Commit**

```bash
git add models.py tests/test_models.py
git commit -m "feat: add model functions for banned URLs and track deletion"
```

---

### Task 3: API Routes for Delete Track and Banned URLs

**Files:**
- Modify: `app.py` (add routes after line 506, before `# --- Stats ---`)
- Test: `tests/test_routes.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_routes.py`:

```python
class TestDeleteTrackRoute:
    def test_delete_track_marks_deleted(self, client, tmp_path):
        import models
        _add_track(
            models, album_id=1, album_title="Album",
            artist_name="Artist", track_title="Song",
            track_number=1, youtube_url="https://yt/abc",
            youtube_title="vid", album_path=str(tmp_path),
        )
        # Create the MP3 file so deletion works
        mp3_path = tmp_path / "01 - Song.mp3"
        mp3_path.write_text("fake mp3")
        tracks = models.get_track_downloads_for_album(1)
        track_id = tracks[0]["id"]
        resp = client.delete(
            f"/api/download/track/{track_id}",
            json={"ban_url": False},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["file_deleted"] is True
        assert data["url_banned"] is False
        assert not mp3_path.exists()
        # DB marked as deleted
        tracks = models.get_track_downloads_for_album(1)
        assert tracks[0]["deleted"] == 1

    def test_delete_track_with_ban(self, client, tmp_path):
        import models
        _add_track(
            models, album_id=1, album_title="Album",
            artist_name="Artist", track_title="Song",
            track_number=1, youtube_url="https://yt/abc",
            youtube_title="vid", album_path=str(tmp_path),
        )
        mp3_path = tmp_path / "01 - Song.mp3"
        mp3_path.write_text("fake mp3")
        tracks = models.get_track_downloads_for_album(1)
        track_id = tracks[0]["id"]
        resp = client.delete(
            f"/api/download/track/{track_id}",
            json={"ban_url": True},
        )
        data = resp.get_json()
        assert data["url_banned"] is True
        banned = models.get_banned_urls_for_track(1, "Song")
        assert "https://yt/abc" in banned

    def test_delete_track_removes_xml_sidecar(self, client, tmp_path):
        import models
        _add_track(
            models, album_id=1, track_title="Song",
            track_number=1, album_path=str(tmp_path),
        )
        mp3_path = tmp_path / "01 - Song.mp3"
        xml_path = tmp_path / "01 - Song.xml"
        mp3_path.write_text("fake mp3")
        xml_path.write_text("<xml/>")
        tracks = models.get_track_downloads_for_album(1)
        resp = client.delete(
            f"/api/download/track/{tracks[0]['id']}",
            json={"ban_url": False},
        )
        assert resp.status_code == 200
        assert not mp3_path.exists()
        assert not xml_path.exists()

    def test_delete_track_file_missing(self, client):
        import models
        _add_track(
            models, album_id=1, track_title="Song",
            track_number=1, album_path="/nonexistent/path",
        )
        tracks = models.get_track_downloads_for_album(1)
        resp = client.delete(
            f"/api/download/track/{tracks[0]['id']}",
            json={"ban_url": False},
        )
        data = resp.get_json()
        assert resp.status_code == 200
        assert data["file_deleted"] is False
        # Still marked deleted in DB
        tracks = models.get_track_downloads_for_album(1)
        assert tracks[0]["deleted"] == 1

    def test_delete_track_not_found(self, client):
        resp = client.delete(
            "/api/download/track/9999",
            json={"ban_url": False},
        )
        assert resp.status_code == 404


class TestBannedUrlsRoutes:
    def test_get_banned_urls_empty(self, client):
        resp = client.get("/api/banned-urls")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_get_banned_urls_with_data(self, client):
        import models
        models.add_banned_url(
            youtube_url="https://yt/abc", youtube_title="vid",
            album_id=1, album_title="A", artist_name="A",
            track_title="T1", track_number=1,
        )
        resp = client.get("/api/banned-urls")
        data = resp.get_json()
        assert data["total"] == 1
        assert data["items"][0]["youtube_url"] == "https://yt/abc"

    def test_remove_banned_url(self, client):
        import models
        models.add_banned_url(
            youtube_url="https://yt/abc", youtube_title="vid",
            album_id=1, album_title="A", artist_name="A",
            track_title="T1", track_number=1,
        )
        bans = models.get_banned_urls(page=1, per_page=50)
        ban_id = bans["items"][0]["id"]
        resp = client.delete(f"/api/banned-urls/{ban_id}")
        assert resp.status_code == 200
        assert resp.get_json()["success"] is True
        assert models.get_banned_urls(page=1, per_page=50)["total"] == 0

    def test_remove_banned_url_not_found(self, client):
        resp = client.delete("/api/banned-urls/9999")
        assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python3 -m pytest tests/test_routes.py::TestDeleteTrackRoute tests/test_routes.py::TestBannedUrlsRoutes -v`

Expected: FAIL — routes don't exist (404)

- [ ] **Step 3: Implement routes**

Add to `app.py` after the `api_album_tracks` route (after line 506), before `# --- Stats ---`:

```python
@app.route("/api/download/track/<int:track_id>", methods=["DELETE"])
def api_delete_track(track_id):
    track_data = models.mark_track_deleted(track_id)
    if track_data is None:
        return jsonify({"success": False, "error": "Track not found"}), 404

    file_deleted = False
    sanitized_track = sanitize_filename(track_data["track_title"])
    track_num = track_data["track_number"]
    album_path = track_data["album_path"]
    mp3_name = f"{track_num:02d} - {sanitized_track}.mp3"
    xml_name = f"{track_num:02d} - {sanitized_track}.xml"
    mp3_path = os.path.join(album_path, mp3_name)
    xml_path = os.path.join(album_path, xml_name)

    try:
        os.remove(mp3_path)
        file_deleted = True
    except FileNotFoundError:
        logger.warning("Track file not found for deletion: %s", mp3_path)
    try:
        os.remove(xml_path)
    except FileNotFoundError:
        pass

    url_banned = False
    body = request.get_json(silent=True) or {}
    if body.get("ban_url") and track_data.get("youtube_url"):
        models.add_banned_url(
            youtube_url=track_data["youtube_url"],
            youtube_title=track_data.get("youtube_title", ""),
            album_id=track_data["album_id"],
            album_title=track_data.get("album_title", ""),
            artist_name=track_data.get("artist_name", ""),
            track_title=track_data["track_title"],
            track_number=track_num,
        )
        url_banned = True

    return jsonify({
        "success": True,
        "file_deleted": file_deleted,
        "url_banned": url_banned,
    })


@app.route("/api/banned-urls")
def api_get_banned_urls():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    return jsonify(models.get_banned_urls(page, per_page))


@app.route("/api/banned-urls/<int:ban_id>", methods=["DELETE"])
def api_remove_banned_url(ban_id):
    deleted = models.remove_banned_url(ban_id)
    if deleted:
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Ban not found"}), 404
```

Verify that `sanitize_filename` is imported from `utils` and `os` is imported at the top of `app.py`. Both should already be present — check and add if missing.

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && python3 -m pytest tests/test_routes.py::TestDeleteTrackRoute tests/test_routes.py::TestBannedUrlsRoutes -v`

Expected: All PASS

- [ ] **Step 5: Run full route test suite**

Run: `source .venv/bin/activate && python3 -m pytest tests/test_routes.py -v`

Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add app.py tests/test_routes.py
git commit -m "feat: add API routes for track deletion and URL banning"
```

---

### Task 4: Downloader — Filter Banned URLs During Search

**Files:**
- Modify: `downloader.py:132-135` (signature), `downloader.py:277-284` (candidate filtering)
- Modify: `processing.py:472-481` (pass banned_urls to download call)
- Test: `tests/test_downloader.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_downloader.py`:

```python
class TestBannedUrlFiltering:
    @patch("downloader.yt_dlp.YoutubeDL")
    @patch("downloader.load_config")
    def test_banned_url_excluded_from_candidates(
        self, mock_config, mock_ydl_class
    ):
        mock_config.return_value = {
            "forbidden_words": [],
            "duration_tolerance": 10,
            "yt_player_client": "android",
        }
        # Simulate search results: banned URL scores higher
        mock_ydl = mock_ydl_class.return_value.__enter__.return_value
        mock_ydl.extract_info.return_value = {
            "entries": [
                {
                    "title": "Artist - Track (Official)",
                    "url": "banned_video_id",
                    "duration": 200,
                    "channel": "Artist",
                    "view_count": 1000000,
                },
                {
                    "title": "Artist - Track Audio",
                    "url": "good_video_id",
                    "duration": 200,
                    "channel": "Artist",
                    "view_count": 500000,
                },
            ]
        }
        mock_ydl.download.return_value = 0

        result = download_track_youtube(
            "Artist Track official audio",
            "/tmp/test_output",
            "Track",
            expected_duration_ms=200000,
            banned_urls={"banned_video_id"},
        )
        # The banned URL should not be selected
        if result and isinstance(result, dict) and result.get("success"):
            assert result.get("youtube_url") != "banned_video_id"

    @patch("downloader.yt_dlp.YoutubeDL")
    @patch("downloader.load_config")
    def test_no_banned_urls_passes_all_candidates(
        self, mock_config, mock_ydl_class
    ):
        """When banned_urls is None or empty, all candidates pass."""
        mock_config.return_value = {
            "forbidden_words": [],
            "duration_tolerance": 10,
            "yt_player_client": "android",
        }
        mock_ydl = mock_ydl_class.return_value.__enter__.return_value
        mock_ydl.extract_info.return_value = {
            "entries": [
                {
                    "title": "Artist - Track",
                    "url": "video_id",
                    "duration": 200,
                    "channel": "Artist",
                    "view_count": 1000000,
                },
            ]
        }
        mock_ydl.download.return_value = 0

        # Should not raise or filter anything
        result = download_track_youtube(
            "Artist Track official audio",
            "/tmp/test_output",
            "Track",
            expected_duration_ms=200000,
            banned_urls=None,
        )
        assert result is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source .venv/bin/activate && python3 -m pytest tests/test_downloader.py::TestBannedUrlFiltering -v`

Expected: FAIL — `download_track_youtube() got unexpected keyword argument 'banned_urls'`

- [ ] **Step 3: Add `banned_urls` parameter to downloader**

In `downloader.py`:

1. Update function signature (line 132-135):

```python
def download_track_youtube(
    query, output_path, track_title_original,
    expected_duration_ms=None, progress_hook=None, skip_check=None,
    banned_urls=None,
):
```

2. Update docstring Args to include:

```
        banned_urls: Optional set of YouTube URL strings to exclude
            from candidates (previously banned by user).
```

3. Add filtering in the search loop. After the duration check block (after the `continue` at line 247, before the `title_score` calculation at line 257), insert:

```python
                    if banned_urls and url in banned_urls:
                        logger.debug(
                            "   Rejected '%s'"
                            " - URL banned by user",
                            entry.get("title", ""),
                        )
                        continue
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source .venv/bin/activate && python3 -m pytest tests/test_downloader.py -v`

Expected: All PASS

- [ ] **Step 5: Wire up in processing.py**

In `processing.py`, inside `_process_single_track()` (the inner function starting at line 426):

1. Before the `_run_download` inner function definition (around line 472), add:

```python
        banned_url_set = models.get_banned_urls_for_track(
            album_id, track_title,
        )
```

Note: `album_id` is available from `album_ctx["album_id"]` which is already extracted at line 410. Verify `models` is imported in `processing.py` (it should be — check for `import models` or `from models import`).

2. Update the `download_track_youtube` call inside `_run_download()` (line 474-481) to pass `banned_urls`:

```python
                dl_result_box[0] = download_track_youtube(
                    f"{artist_name} {track_title} official audio",
                    temp_file,
                    track_title,
                    track_duration_ms,
                    progress_hook=progress_hook,
                    skip_check=_skip_check,
                    banned_urls=banned_url_set,
                )
```

- [ ] **Step 6: Run full test suite**

Run: `source .venv/bin/activate && python3 -m pytest tests/ -v`

Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add downloader.py processing.py tests/test_downloader.py
git commit -m "feat: filter banned URLs during YouTube search"
```

---

### Task 5: Downloads Page UI — Delete Button and Confirmation Dialog

**Files:**
- Modify: `templates/downloads.html`

This task is UI-only. Manual verification via TESTING.md.

- [ ] **Step 1: Add CSS for deleted tracks and modal**

In `templates/downloads.html`, inside the `<style>` block, add styles for: `.track-deleted`, `.deleted-badge`, `.btn-delete-track`, `.modal-overlay`, `.modal-box`, `.modal-title`, `.modal-subtitle`, `.file-path-label`, `.file-path-box`, `.xml-note`, `.ban-checkbox`, `.ban-checkbox-text`, `.modal-actions`.

Update `.track-detail-header` and `.track-detail-row` grid-template-columns to 8 columns:
```css
grid-template-columns: 40px 1.5fr 2fr 60px 70px 55px 100px 40px;
```

Full CSS additions:

```css
.track-detail-row.track-deleted {
    background: rgba(239,68,68,0.06);
}
.track-detail-row.track-deleted .track-title-text {
    text-decoration: line-through;
    color: var(--text-dim);
}
.deleted-badge {
    display: inline-block;
    font-size: 0.65rem;
    color: var(--danger);
    background: rgba(239,68,68,0.15);
    padding: 1px 6px;
    border-radius: 4px;
    margin-left: 6px;
}
.btn-delete-track {
    background: none;
    border: none;
    color: var(--text-dim);
    cursor: pointer;
    padding: 4px 6px;
    border-radius: 6px;
    transition: all 0.15s;
    font-size: 0.8rem;
}
.btn-delete-track:hover {
    color: var(--danger);
    background: rgba(239,68,68,0.15);
}
.modal-overlay {
    position: fixed;
    inset: 0;
    background: rgba(0,0,0,0.6);
    backdrop-filter: blur(4px);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 100;
}
.modal-overlay.hidden { display: none; }
.modal-box {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 1.5rem;
    max-width: 480px;
    width: 90%;
    box-shadow: var(--shadow);
}
.modal-title {
    font-size: 1rem;
    font-weight: 600;
    margin-bottom: 0.25rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
}
.modal-title i { color: var(--danger); }
.modal-subtitle {
    color: var(--text-dim);
    font-size: 0.8rem;
    margin-bottom: 1rem;
}
.file-path-label {
    font-size: 0.7rem;
    text-transform: uppercase;
    color: var(--text-dim);
    letter-spacing: 0.05em;
    margin-bottom: 0.3rem;
    font-weight: 600;
}
.file-path-box {
    background: rgba(0,0,0,0.3);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 0.6rem 0.75rem;
    font-family: 'SF Mono', 'Fira Code', monospace;
    font-size: 0.75rem;
    color: var(--text-dim);
    word-break: break-all;
    margin-bottom: 0.5rem;
}
.xml-note {
    font-size: 0.7rem;
    color: var(--text-dim);
    font-style: italic;
    margin-bottom: 1rem;
}
.ban-checkbox {
    display: flex;
    align-items: flex-start;
    gap: 0.6rem;
    background: rgba(239,68,68,0.06);
    border: 1px solid rgba(239,68,68,0.2);
    border-radius: 8px;
    padding: 0.75rem;
    margin: 1rem 0;
    cursor: pointer;
}
.ban-checkbox input[type="checkbox"] {
    margin-top: 2px;
    accent-color: var(--danger);
    width: 16px;
    height: 16px;
    flex-shrink: 0;
}
.ban-checkbox-text { font-size: 0.8rem; }
.ban-checkbox-text strong { color: var(--danger); }
.ban-checkbox-text .ban-detail {
    color: var(--text-dim);
    font-size: 0.7rem;
    margin-top: 2px;
}
.modal-actions {
    display: flex;
    gap: 0.5rem;
    justify-content: flex-end;
    margin-top: 1rem;
}
```

- [ ] **Step 2: Add modal HTML**

Before the closing `</body>` tag in `downloads.html`, add the delete track modal markup. All dynamic content is set via `textContent` in JS (no innerHTML with user data):

```html
<div class="modal-overlay hidden" id="deleteTrackModal" onclick="if(event.target===this)closeDeleteModal()">
    <div class="modal-box">
        <div class="modal-title"><i class="fas fa-trash-alt"></i> Delete Track</div>
        <div class="modal-subtitle">This will permanently remove the downloaded file from disk.</div>
        <div class="file-path-label">File location</div>
        <div class="file-path-box" id="deleteModalPath"></div>
        <div class="xml-note">The XML sidecar file will also be removed if present.</div>
        <label class="ban-checkbox">
            <input type="checkbox" id="banUrlCheckbox" checked>
            <div class="ban-checkbox-text">
                <strong>Ban this URL from future downloads</strong>
                <div class="ban-detail" id="banUrlDetail"></div>
            </div>
        </label>
        <div class="modal-actions">
            <button class="btn btn-outline" onclick="closeDeleteModal()">Cancel</button>
            <button class="btn btn-danger" id="confirmDeleteBtn"><i class="fas fa-trash"></i> Delete Track</button>
        </div>
    </div>
</div>
```

- [ ] **Step 3: Update track grid to 8 columns and add actions column**

In the `renderTrackGrid` function:

1. Update the header columns array (around line 1551):
```javascript
['#', 'Track', 'YouTube Source', 'Score', 'AcoustID', 'Dur.', 'Downloaded', ''].forEach(function(text) {
```

2. In the `sorted.forEach` loop, modify the title cell to handle deleted state (replace the existing titleCell creation around line 1570-1579):

```javascript
var titleCell = document.createElement('div');
if (t.deleted) {
    detailRow.classList.add('track-deleted');
    var titleSpan = document.createElement('span');
    titleSpan.className = 'track-title-text';
    titleSpan.textContent = t.track_title;
    titleCell.appendChild(titleSpan);
    var delBadge = document.createElement('span');
    delBadge.className = 'deleted-badge';
    delBadge.textContent = 'deleted';
    titleCell.appendChild(delBadge);
} else {
    titleCell.style.color = isFailed ? 'var(--danger)' : 'var(--text)';
    titleCell.textContent = t.track_title;
    if (attemptCount > 1) {
        var attemptBadge = document.createElement('span');
        attemptBadge.className = 'track-attempts';
        attemptBadge.title = attemptCount + ' download attempts';
        attemptBadge.textContent = '(' + attemptCount + ' attempts)';
        titleCell.appendChild(attemptBadge);
    }
}
detailRow.appendChild(titleCell);
```

3. For deleted tracks, dim the YouTube link. In the ytCell section (around line 1589), after creating the link element, add:
```javascript
if (t.deleted) {
    link.style.opacity = '0.5';
}
```

4. After the timeCell append (after line 1641), before `fragment.appendChild(detailRow)`, add the actions cell:

```javascript
var actionsCell = document.createElement('div');
if (t.success && !t.deleted) {
    var delBtn = document.createElement('button');
    delBtn.className = 'btn-delete-track';
    delBtn.title = 'Delete track file';
    delBtn.innerHTML = '<i class="fas fa-trash"></i>';
    delBtn.onclick = function(e) {
        e.stopPropagation();
        openDeleteModal({
            id: t.id,
            trackTitle: t.track_title,
            trackNumber: t.track_number,
            albumPath: t.album_path,
            youtubeUrl: t.youtube_url,
            youtubeTitle: t.youtube_title,
            artistName: t.artist_name,
            albumId: albumId,
        });
    };
    actionsCell.appendChild(delBtn);
}
detailRow.appendChild(actionsCell);
```

- [ ] **Step 4: Add modal JavaScript functions**

Add to the `<script>` block in `downloads.html`:

```javascript
var _deleteModalData = null;

function openDeleteModal(data) {
    _deleteModalData = data;
    var num = String(data.trackNumber).padStart(2, '0');
    var filename = num + ' - ' + data.trackTitle + '.mp3';
    var path = data.albumPath ? data.albumPath + '/' + filename : filename;
    document.getElementById('deleteModalPath').textContent = path;
    var urlText = data.youtubeUrl || 'unknown';
    document.getElementById('banUrlDetail').textContent =
        'The URL ' + urlText + ' will be skipped when searching for "' +
        data.trackTitle + '" in future downloads.';
    document.getElementById('banUrlCheckbox').checked = true;
    document.getElementById('deleteTrackModal').classList.remove('hidden');
    document.getElementById('confirmDeleteBtn').onclick = confirmDeleteTrack;
}

function closeDeleteModal() {
    document.getElementById('deleteTrackModal').classList.add('hidden');
    _deleteModalData = null;
}

async function confirmDeleteTrack() {
    if (!_deleteModalData) return;
    var data = _deleteModalData;
    var banUrl = document.getElementById('banUrlCheckbox').checked;
    closeDeleteModal();
    try {
        var resp = await fetch('/api/download/track/' + data.id, {
            method: 'DELETE',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ban_url: banUrl}),
        });
        if (resp.ok) {
            var grid = document.getElementById('tracks-' + data.albumId);
            if (grid) await renderTrackGrid(grid, data.albumId);
        } else {
            alert('Failed to delete track');
        }
    } catch (e) {
        console.error('Delete track error:', e);
        alert('Failed to delete track');
    }
}
```

- [ ] **Step 5: Commit**

```bash
git add templates/downloads.html
git commit -m "feat: add delete track button and confirmation dialog to downloads UI"
```

---

### Task 6: Logs Page UI — Banned URL Filter and Unban

**Files:**
- Modify: `templates/logs.html`

- [ ] **Step 1: Add filter dropdown option**

In `templates/logs.html`, in the filter select (line 765-775), add before `</select>`:

```html
<option value="url_banned">URL Banned</option>
```

- [ ] **Step 2: Add `url_banned` to log type info and CSS**

In `getLogTypeInfo` (line 983-994), add:
```javascript
'url_banned': { name: 'URL Banned', icon: 'fa-ban' },
```

Add CSS:
```css
.log-card.url_banned { border-left-color: #f97316; }
.log-type.url_banned {
    color: #f97316;
    background: rgba(249,115,22,0.12);
}
.btn-unban {
    background: none;
    border: 1px solid #f97316;
    color: #f97316;
    padding: 0.3rem 0.75rem;
    border-radius: 6px;
    font-size: 0.75rem;
    cursor: pointer;
    font-weight: 500;
    transition: all 0.15s;
    display: flex;
    align-items: center;
    gap: 0.3rem;
}
.btn-unban:hover { background: rgba(249,115,22,0.12); }
.ban-url-link {
    color: var(--primary);
    text-decoration: none;
    font-size: 0.8rem;
    word-break: break-all;
}
.ban-url-link:hover { text-decoration: underline; }
```

- [ ] **Step 3: Update fetchLogs to handle `url_banned` filter**

At the start of the `fetchLogs` function (around line 935), add a branch:

```javascript
if (currentFilter === 'url_banned') {
    const res = await fetch(
        '/api/banned-urls?page=' + logsCurrentPage + '&per_page=' + LOGS_PER_PAGE
    );
    const data = await res.json();
    logsTotalPages = data.pages;
    logsTotal = data.total;
    var transformed = data.items.map(function(ban) {
        return {
            id: 'ban_' + ban.id,
            _ban_id: ban.id,
            type: 'url_banned',
            album_id: ban.album_id,
            album_title: ban.album_title,
            artist_name: ban.artist_name,
            timestamp: ban.banned_at,
            youtube_url: ban.youtube_url,
            track_title: ban.track_title,
            track_number: ban.track_number,
        };
    });
    renderLogs(transformed, data.total);
    return;
}
```

- [ ] **Step 4: Update renderLogCard for banned URL entries**

At the top of `renderLogCard` (line 998), add an early return for `url_banned` type. Use `textContent`-based DOM construction or ensure all interpolated values go through `escapeHtml()`:

```javascript
if (log.type === 'url_banned') {
    var safeUrl = sanitizeUrl(log.youtube_url);
    var urlHtml = safeUrl
        ? '<a class="ban-url-link" href="' + escapeHtml(safeUrl) + '" target="_blank" rel="noopener">' + escapeHtml(log.youtube_url) + '</a>'
        : escapeHtml(log.youtube_url || '');
    var trackNum = log.track_number
        ? String(log.track_number).padStart(2, '0') + ' - '
        : '';
    return '<div class="log-card url_banned" id="log-' + escapeHtml(log.id) + '">'
        + '<div class="log-header">'
        + '<div class="log-info">'
        + '<div class="log-type url_banned"><i class="fas fa-ban"></i> URL Banned</div>'
        + '<div class="log-album">' + escapeHtml(log.track_title || log.album_title) + '</div>'
        + '<div class="log-artist">by ' + escapeHtml(log.artist_name) + '</div>'
        + '</div>'
        + '<div class="log-actions">'
        + '<button class="btn-unban" onclick="unbanUrl(' + log._ban_id + ',\'' + escapeHtml(log.id) + '\')">'
        + '<i class="fas fa-unlock"></i> Unban</button>'
        + '</div></div>'
        + '<div class="log-details">'
        + '<div class="log-details-title">Banned URL:</div>'
        + urlHtml
        + '<div style="margin-top:0.3rem;font-size:0.75rem;">Track: <strong style="color:var(--text)">'
        + escapeHtml(trackNum + (log.track_title || '')) + '</strong></div>'
        + '</div>'
        + '<div class="log-timestamp"><i class="fas fa-clock"></i> '
        + formatTimestamp(log.timestamp) + '</div></div>';
}
```

- [ ] **Step 5: Add unbanUrl function and sanitizeUrl if missing**

Add `unbanUrl` to the `<script>` block:

```javascript
async function unbanUrl(banId, logElementId) {
    try {
        var resp = await fetch('/api/banned-urls/' + banId, {
            method: 'DELETE',
        });
        if (resp.ok) {
            var card = document.getElementById('log-' + logElementId);
            if (card) {
                card.style.animation = 'slideOut 0.3s ease forwards';
                setTimeout(function() { fetchLogs(); }, 300);
            }
        } else {
            alert('Failed to unban URL');
        }
    } catch (e) {
        console.error('Unban error:', e);
        alert('Failed to unban URL');
    }
}
```

Check if `sanitizeUrl` exists in `logs.html`. If not, add:

```javascript
function sanitizeUrl(url) {
    if (!url) return '';
    try {
        var u = new URL(url);
        if (u.protocol === 'https:' || u.protocol === 'http:') return url;
    } catch (_) {}
    return '';
}
```

- [ ] **Step 6: Commit**

```bash
git add templates/logs.html
git commit -m "feat: add URL Banned filter type and unban button to logs page"
```

---

### Task 7: Update TESTING.md with Manual Test Cases

**Files:**
- Modify: `TESTING.md`

- [ ] **Step 1: Add manual test cases**

Add a new section to `TESTING.md`:

```markdown
## Delete Track + Ban URL Tests

Run after changes to track deletion, URL banning, or related UI:

- [ ] **Downloads page**: Expand album in history — successful tracks show trash icon
- [ ] **Downloads page**: Failed tracks and deleted tracks do NOT show trash icon
- [ ] **Downloads page**: Click trash icon — confirmation dialog appears with correct file path
- [ ] **Downloads page**: Dialog shows XML sidecar note
- [ ] **Downloads page**: Ban checkbox is checked by default
- [ ] **Downloads page**: Confirm delete (with ban) — file removed, track shows strikethrough + "deleted" badge
- [ ] **Downloads page**: Confirm delete (without ban) — file removed, track deleted but no ban created
- [ ] **Downloads page**: Deleted track has dimmed YouTube link, no trash icon
- [ ] **Downloads page**: Cancel button closes dialog without action
- [ ] **Downloads page**: Click outside modal closes dialog
- [ ] **Logs page**: "URL Banned" option appears in filter dropdown
- [ ] **Logs page**: Select "URL Banned" filter — shows banned URL cards with orange accent
- [ ] **Logs page**: Banned URL card shows YouTube link, track context, and Unban button
- [ ] **Logs page**: Click Unban — card slides out and disappears
- [ ] **Logs page**: After unban, switching away and back to "URL Banned" filter confirms it's gone
- [ ] **Re-download**: Queue previously downloaded album — deleted track re-downloads with different URL (banned one skipped)
- [ ] **Re-download**: Unban a URL, re-download — previously banned URL is now a candidate again
```

- [ ] **Step 2: Commit**

```bash
git add TESTING.md
git commit -m "docs: add manual test cases for delete track and ban URL feature"
```

---

### Task 8: Final Integration Verification

- [ ] **Step 1: Run full test suite**

Run: `source .venv/bin/activate && python3 -m pytest tests/ -v`

Expected: All PASS

- [ ] **Step 2: Build and run Docker**

Run: `docker compose up -d --build`

Wait for build to complete, then verify at http://localhost:5000.

- [ ] **Step 3: Smoke test the feature**

1. Navigate to Downloads page
2. Expand an album with downloaded tracks
3. Verify trash icons appear on successful tracks
4. Click trash on a track — verify dialog shows
5. Confirm with ban checked — verify file deleted and track shows "deleted"
6. Go to Logs page, select "URL Banned" filter
7. Verify banned URL card appears
8. Click Unban — verify card disappears
9. Stop containers: `docker compose down`

- [ ] **Step 4: Commit any final fixes**

If any issues found during smoke testing, fix and commit.
