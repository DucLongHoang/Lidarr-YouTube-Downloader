# Delete Track + Ban URL — Design Spec

## Overview

Allow users to delete downloaded tracks from disk and optionally ban the YouTube URL from being selected again for that specific track. This addresses the case where yt-dlp downloads the wrong song — the user can remove it and ensure the same source isn't picked again on re-download.

## User Flow

1. User expands an album in Download History and sees individual tracks with a **delete button** (trash icon) on each successfully downloaded track row.
2. Clicking delete opens a **confirmation dialog** showing:
   - The full file path of the MP3 being deleted.
   - A note that the XML sidecar will also be removed if present.
   - A checkbox (checked by default): **"Ban this URL from future downloads"** with detail text showing the track-scoped ban.
3. On confirm:
   - The MP3 file is deleted from disk.
   - The XML sidecar file is deleted if it exists.
   - The `track_downloads` row is marked `deleted = 1`.
   - If the ban checkbox is checked, a row is inserted into `banned_urls`.
4. The track row in history updates to show a strikethrough title, "deleted" badge, and dimmed YouTube link. The delete button is removed.
5. When the album is re-queued for download, the deleted track is treated as missing. During YouTube search, any banned URLs for that track are filtered out of candidates.

## Unbanning

- The Logs page has a new filter type: **"URL Banned"** (orange accent).
- Each banned URL entry shows the URL, album, artist, and track context.
- An **"Unban"** button removes the `banned_urls` row entirely — the entry disappears from logs.
- The `deleted` flag on `track_downloads` is **not** affected by unbanning. The track still shows as deleted in history.

## Database Changes

### New table: `banned_urls`

```sql
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
);
CREATE INDEX idx_banned_urls_lookup ON banned_urls(album_id, track_title);
CREATE INDEX idx_banned_urls_timestamp ON banned_urls(banned_at);
```

The `UNIQUE(youtube_url, album_id, track_title)` constraint ensures the same URL can only be banned once per track. Since bans are track-scoped, the same URL can be a valid candidate for other tracks.

### Modified table: `track_downloads`

Add column via migration:

```sql
ALTER TABLE track_downloads ADD COLUMN deleted INTEGER DEFAULT 0;
```

### Migration: V3 to V4

- Increment `SCHEMA_VERSION` to `4` in `db.py`.
- Add `migrate_v3_to_v4(conn)` function.
- Register in `_run_migrations()` dict.

## API Endpoints

### `DELETE /api/download/track/<int:track_id>`

Delete a track's file from disk and optionally ban its URL.

**Request body:**
```json
{
    "ban_url": true
}
```

**Behavior:**
1. Look up `track_downloads` row by `id`.
2. Reconstruct file path from `album_path`, `track_number`, and `track_title`.
3. Delete the MP3 file. Delete the XML sidecar if it exists (same name, `.xml` extension).
4. Set `deleted = 1` on the `track_downloads` row.
5. If `ban_url` is true and `youtube_url` is present, insert into `banned_urls`.

**Response:**
```json
{
    "success": true,
    "file_deleted": true,
    "url_banned": true
}
```

**Error cases:**
- Track not found → 404
- File not found on disk → Still marks `deleted = 1` and bans URL if requested. Returns `"file_deleted": false`.

**Out of scope:** Triggering a Lidarr rescan after deletion. The file may have already been imported and moved by Lidarr. Users manage Lidarr's library state through Lidarr itself.

### `GET /api/banned-urls`

List all banned URLs with pagination.

**Query params:** `page`, `per_page`

**Response:** Standard paginated response with items from `banned_urls` table, ordered by `banned_at DESC`.

### `DELETE /api/banned-urls/<int:ban_id>`

Remove a ban. Deletes the row from `banned_urls`.

**Response:**
```json
{
    "success": true
}
```

## Model Functions

### `models.py` additions

- `delete_track_file(track_id)` — Sets `deleted = 1`, returns the track row data needed for file path reconstruction.
- `add_banned_url(youtube_url, youtube_title, album_id, album_title, artist_name, track_title, track_number)` — Inserts into `banned_urls`. Uses `INSERT OR IGNORE` to handle duplicate bans gracefully.
- `get_banned_urls(page, per_page)` — Paginated query on `banned_urls` ordered by `banned_at DESC`.
- `get_banned_urls_for_track(album_id, track_title)` — Returns list of banned YouTube URLs for a specific track. Used by the downloader to filter candidates.
- `remove_banned_url(ban_id)` — Deletes from `banned_urls`.

## Downloader Integration

In `downloader.py`, within `download_track_youtube()`:

Current signature: `download_track_youtube(query, output_path, track_title_original, expected_duration_ms=None, progress_hook=None, skip_check=None)`.

Add a new optional parameter `banned_urls=None` — a `set` of YouTube URL strings to skip. This keeps the downloader decoupled from the database; the caller (`processing.py`) is responsible for fetching the banned URLs via `models.get_banned_urls_for_track(album_id, track_title)` and passing the set in.

- In `processing.py`'s `_process_single_track()`, before calling `download_track_youtube()`, call `models.get_banned_urls_for_track(album_id, track_title)` and pass the result as `banned_urls`.
- In the search loop (around line 277), after duration/forbidden checks and before `candidates.append(...)`, check if the candidate URL is in the `banned_urls` set. If so, skip it.
- The `album_path` column exists in `track_downloads` (db.py:185), confirming file path reconstruction is supported.

## Logs Page Integration

The Logs page currently queries only the `download_logs` table. For the "URL Banned" filter type:

- When filter is `"url_banned"`: Query `banned_urls` table instead of `download_logs`. Transform rows into the log card format expected by the frontend.
- When filter is `"all"`: Query both tables and merge by timestamp. Alternatively, keep them separate and only show banned URLs when explicitly filtered (simpler).

**Recommendation:** Only show banned URL entries when the "URL Banned" filter is selected. Don't mix them into "All Types" — they're a different data source and would complicate pagination. The "All Types" view stays focused on download events.

## UI Changes

### `downloads.html` — Track Detail Grid

- Add 8th column header: empty (for the action button).
- Grid template changes from 7 columns to 8: add `40px` column at the end.
- For each successful, non-deleted track: render a trash icon button that calls `deleteTrack(trackId, trackTitle, albumPath, trackNumber, youtubeUrl, youtubeTitle)`.
- For deleted tracks (`deleted === 1`): render strikethrough title, "deleted" badge, dimmed YouTube link, no delete button.
- The `renderTrackGrid()` function needs the `deleted` field from the API response. The `GET /api/download/history/<album_id>/tracks` endpoint calls `models.get_track_downloads_for_album()` which uses `SELECT *` on `track_downloads`. After the V4 migration adds the `deleted` column, it will be included in responses automatically. Verify during implementation that the endpoint returns `deleted` correctly.

### `downloads.html` — Confirmation Dialog

- New modal HTML appended to the page (hidden by default).
- `deleteTrack()` function:
  1. Reconstructs the display file path from track metadata.
  2. Populates the modal with file path, track name, and YouTube URL context.
  3. Shows the modal.
- "Cancel" closes the modal.
- "Delete Track" sends `DELETE /api/download/track/<id>` with `{ "ban_url": <checkbox_state> }`.
- On success: re-renders the track grid for that album.

### `logs.html` — Filter Dropdown

- Add `<option value="url_banned">URL Banned</option>` to the filter select.

### `logs.html` — Log Card Rendering

- Add `url_banned` to `getLogTypeInfo()`: `{ name: 'URL Banned', icon: 'fa-ban' }`.
- When rendering a `url_banned` card:
  - Orange left border (`border-left-color: #f97316`).
  - Show banned URL as a clickable link.
  - Show track context (track number + title).
  - Replace the dismiss button with an "Unban" button.
  - "Unban" calls `DELETE /api/banned-urls/<id>` and removes the card with slide-out animation.

### `logs.html` — Fetch Logic

- When `currentFilter === 'url_banned'`: fetch from `GET /api/banned-urls` instead of `GET /api/logs`.
- Transform the response to match the log card data shape expected by `renderLogCard()` (or use a separate render function for banned URL cards).

## File Deletion Logic

Reconstruct the file path:

```python
sanitized_track = sanitize_filename(track_title)
filename = f"{track_number:02d} - {sanitized_track}.mp3"
file_path = os.path.join(album_path, filename)
xml_path = os.path.join(album_path, f"{track_number:02d} - {sanitized_track}.xml")
```

Use `os.remove()` for deletion. Handle `FileNotFoundError` gracefully (file may have been moved/deleted externally).

## Testing

### Unit tests
- `test_db.py`: V3→V4 migration creates `banned_urls` table and adds `deleted` column.
- `test_models.py`: CRUD operations for `banned_urls`, `delete_track_file()`, `get_banned_urls_for_track()`.
- `test_downloader.py`: Banned URLs are filtered from candidates during search.
- `test_routes.py`: `DELETE /api/download/track/<id>`, `GET /api/banned-urls`, `DELETE /api/banned-urls/<id>`.

### Integration tests
- Delete a track → file removed from disk, `deleted = 1` in DB.
- Delete + ban → banned_urls row created, URL filtered on next download.
- Unban → banned_urls row removed, URL available again for search.
- Delete when file already missing → graceful handling, DB still updated.

### Manual tests (add to TESTING.md)
- Delete button appears on successful tracks, not on failed/deleted tracks.
- Confirmation dialog shows correct file path.
- Ban checkbox default state (checked).
- Deleted track row styling (strikethrough, badge, dimmed link).
- "URL Banned" filter in logs shows only banned URLs.
- Unban button removes the card.
- Re-download of album picks different URL for previously banned track.
