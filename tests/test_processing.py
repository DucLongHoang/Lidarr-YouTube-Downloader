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


def _make_album_ctx(**overrides):
    """Build a default album_ctx dict, overriding any keys."""
    ctx = {
        "artist_name": "Artist",
        "album_title": "Album",
        "album_id": 42,
        "album_mbid": "mbid",
        "artist_mbid": "artist_mbid",
        "cover_data": None,
        "cover_url": "",
        "lidarr_album_path": "",
    }
    ctx.update(overrides)
    return ctx


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

        def create_mp3(*args, **kwargs):
            temp_path = args[1]
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
        download_process["tracks"] = [
            {"track_title": track["title"],
             "track_number": int(track["trackNumber"]),
             "status": "pending", "youtube_url": "", "youtube_title": "",
             "progress_percent": "", "progress_speed": "",
             "error_message": "", "skip": False},
        ]
        download_process["current_track_index"] = -1

        album_ctx = _make_album_ctx(
            cover_url="http://cover.jpg",
            lidarr_album_path="/music/a",
        )
        failed, size = _download_tracks(
            [track], album_path, album, album_ctx,
        )

        assert len(failed) == 0
        tracks = models.get_track_downloads_for_album(42)
        assert len(tracks) == 1
        assert tracks[0]["success"] == 1
        assert tracks[0]["youtube_url"] == (
            "https://youtube.com/watch?v=abc"
        )
        download_process["tracks"] = []
        download_process["current_track_index"] = -1

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
        download_process["tracks"] = [
            {"track_title": track["title"],
             "track_number": int(track["trackNumber"]),
             "status": "pending", "youtube_url": "", "youtube_title": "",
             "progress_percent": "", "progress_speed": "",
             "error_message": "", "skip": False},
        ]
        download_process["current_track_index"] = -1

        failed, size = _download_tracks(
            [track], album_path, {"tracks": [track]},
            _make_album_ctx(),
        )

        assert len(failed) == 1
        tracks = models.get_track_downloads_for_album(42)
        assert len(tracks) == 1
        assert tracks[0]["success"] == 0
        assert tracks[0]["error_message"] == "No suitable match"
        download_process["tracks"] = []
        download_process["current_track_index"] = -1


class TestTrackStateModel:
    """download_process tracks list and TrackSkippedException."""

    def test_download_process_has_tracks_list(self):
        from processing import download_process
        assert "tracks" in download_process
        assert isinstance(download_process["tracks"], list)
        assert download_process["current_track_index"] == -1

    def test_download_process_no_legacy_fields(self):
        from processing import download_process
        assert "progress" not in download_process
        assert "current_track_title" not in download_process

    def test_track_skipped_exception_exists(self):
        from processing import TrackSkippedException
        assert issubclass(TrackSkippedException, Exception)

    def test_update_progress_sets_track_fields(self):
        from processing import download_process, update_progress
        download_process["tracks"] = [
            {"track_title": "T1", "track_number": 1, "status": "downloading",
             "youtube_url": "", "youtube_title": "",
             "progress_percent": "", "progress_speed": "",
             "error_message": "", "skip": False},
        ]
        download_process["current_track_index"] = 0
        update_progress({
            "status": "downloading",
            "_percent_str": " 45.2% ",
            "_speed_str": " 2.4MiB/s ",
        })
        track = download_process["tracks"][0]
        assert track["progress_percent"] == "45.2%"
        assert track["progress_speed"] == "2.4MiB/s"
        # cleanup
        download_process["tracks"] = []
        download_process["current_track_index"] = -1

    def test_update_progress_sets_downloading_status(self):
        from processing import download_process, update_progress
        download_process["tracks"] = [
            {"track_title": "T1", "track_number": 1, "status": "searching",
             "youtube_url": "", "youtube_title": "",
             "progress_percent": "", "progress_speed": "",
             "error_message": "", "skip": False},
        ]
        download_process["current_track_index"] = 0
        update_progress({
            "status": "downloading",
            "_percent_str": "10%",
            "_speed_str": "1MiB/s",
        })
        assert download_process["tracks"][0]["status"] == "downloading"
        download_process["tracks"] = []
        download_process["current_track_index"] = -1

    def test_update_progress_raises_on_skip_flag(self):
        from processing import (
            TrackSkippedException, download_process, update_progress,
        )
        download_process["tracks"] = [
            {"track_title": "T1", "track_number": 1, "status": "downloading",
             "youtube_url": "", "youtube_title": "",
             "progress_percent": "", "progress_speed": "",
             "error_message": "", "skip": True},
        ]
        download_process["current_track_index"] = 0
        with pytest.raises(TrackSkippedException):
            update_progress({"status": "downloading",
                             "_percent_str": "10%", "_speed_str": "1MiB/s"})
        # cleanup
        download_process["tracks"] = []
        download_process["current_track_index"] = -1


class TestTrackStateTransitions:
    """_download_tracks populates tracks list and handles skip."""

    @patch("processing.download_track_youtube")
    @patch("processing.tag_mp3")
    @patch("processing.create_xml_metadata")
    @patch("processing.load_config", return_value={"xml_metadata_enabled": False})
    def test_tracks_state_transitions(
        self, mock_config, mock_xml, mock_tag, mock_dl, tmp_path,
    ):
        from processing import _download_tracks, download_process

        def create_mp3(*args, **kwargs):
            temp_path = args[1]
            open(temp_path + ".mp3", "w").close()
            return {
                "success": True,
                "youtube_url": "https://youtube.com/watch?v=abc",
                "youtube_title": "Title",
                "match_score": 0.9,
                "duration_seconds": 200,
            }
        mock_dl.side_effect = create_mp3
        album_path = str(tmp_path / "album")
        os.makedirs(album_path)
        tracks = [
            {"title": "Track 1", "trackNumber": 1, "duration": 200000},
            {"title": "Track 2", "trackNumber": 2, "duration": 180000},
        ]
        download_process["tracks"] = [
            {"track_title": t["title"], "track_number": int(t["trackNumber"]),
             "status": "pending", "youtube_url": "", "youtube_title": "",
             "progress_percent": "", "progress_speed": "",
             "error_message": "", "skip": False}
            for t in tracks
        ]
        download_process["current_track_index"] = -1
        download_process["stop"] = False
        failed, size = _download_tracks(
            tracks, album_path, {}, _make_album_ctx(),
        )
        assert len(failed) == 0
        assert download_process["tracks"][0]["status"] == "done"
        assert download_process["tracks"][1]["status"] == "done"
        assert download_process["tracks"][0]["youtube_url"] == (
            "https://youtube.com/watch?v=abc"
        )
        download_process["tracks"] = []
        download_process["current_track_index"] = -1

    @patch("processing.download_track_youtube")
    def test_pre_skipped_track_never_downloads(self, mock_dl, tmp_path):
        from processing import _download_tracks, download_process
        album_path = str(tmp_path / "album")
        os.makedirs(album_path)
        tracks = [
            {"title": "Track 1", "trackNumber": 1, "duration": 200000},
        ]
        download_process["tracks"] = [
            {"track_title": "Track 1", "track_number": 1,
             "status": "pending", "youtube_url": "", "youtube_title": "",
             "progress_percent": "", "progress_speed": "",
             "error_message": "", "skip": True},
        ]
        download_process["current_track_index"] = -1
        download_process["stop"] = False
        failed, size = _download_tracks(
            tracks, album_path, {}, _make_album_ctx(),
        )
        mock_dl.assert_not_called()
        assert download_process["tracks"][0]["status"] == "skipped"
        download_process["tracks"] = []
        download_process["current_track_index"] = -1

    @patch("processing.download_track_youtube")
    def test_stop_all_still_stops(self, mock_dl, tmp_path):
        from processing import _download_tracks, download_process
        download_process["stop"] = True
        album_path = str(tmp_path / "album")
        os.makedirs(album_path)
        tracks = [
            {"title": "Track 1", "trackNumber": 1, "duration": 200000},
        ]
        download_process["tracks"] = [
            {"track_title": "Track 1", "track_number": 1,
             "status": "pending", "youtube_url": "", "youtube_title": "",
             "progress_percent": "", "progress_speed": "",
             "error_message": "", "skip": False},
        ]
        download_process["current_track_index"] = -1
        failed, size = _download_tracks(
            tracks, album_path, {}, _make_album_ctx(),
        )
        mock_dl.assert_not_called()
        download_process["tracks"] = []
        download_process["current_track_index"] = -1
        download_process["stop"] = False

    @patch("processing.download_track_youtube")
    def test_skip_during_download_sets_skipped(self, mock_dl, tmp_path):
        from processing import (
            TrackSkippedException, _download_tracks, download_process,
        )
        album_path = str(tmp_path / "album")
        os.makedirs(album_path)
        tracks = [
            {"title": "Track 1", "trackNumber": 1, "duration": 200000},
        ]
        mock_dl.side_effect = TrackSkippedException()
        download_process["tracks"] = [
            {"track_title": "Track 1", "track_number": 1,
             "status": "pending", "youtube_url": "", "youtube_title": "",
             "progress_percent": "", "progress_speed": "",
             "error_message": "", "skip": False},
        ]
        download_process["current_track_index"] = -1
        download_process["stop"] = False
        failed, size = _download_tracks(
            tracks, album_path, {}, _make_album_ctx(),
        )
        assert len(failed) == 0
        assert download_process["tracks"][0]["status"] == "skipped"
        download_process["tracks"] = []
        download_process["current_track_index"] = -1

    @patch("processing.download_track_youtube")
    def test_skipped_result_sets_skipped(self, mock_dl, tmp_path):
        from processing import _download_tracks, download_process
        album_path = str(tmp_path / "album")
        os.makedirs(album_path)
        tracks = [
            {"title": "Track 1", "trackNumber": 1, "duration": 200000},
        ]
        mock_dl.return_value = {"skipped": True}
        download_process["tracks"] = [
            {"track_title": "Track 1", "track_number": 1,
             "status": "pending", "youtube_url": "", "youtube_title": "",
             "progress_percent": "", "progress_speed": "",
             "error_message": "", "skip": False},
        ]
        download_process["current_track_index"] = -1
        download_process["stop"] = False
        failed, size = _download_tracks(
            tracks, album_path, {}, _make_album_ctx(),
        )
        assert len(failed) == 0
        assert download_process["tracks"][0]["status"] == "skipped"
        download_process["tracks"] = []
        download_process["current_track_index"] = -1
