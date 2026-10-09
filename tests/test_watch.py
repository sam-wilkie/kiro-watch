#!/usr/bin/env python3
"""Tests for the kiro-watch perception pipeline (pure/unit scope)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import watch as pipeline  # noqa: E402


class TestIsUrl:
    def test_http_url_is_url(self):
        assert pipeline.is_url("http://example.com/v.mp4") is True

    def test_https_url_is_url(self):
        assert pipeline.is_url("https://youtu.be/abc") is True

    def test_local_path_is_not_url(self):
        assert pipeline.is_url("/Users/sam/video.mp4") is False

    def test_relative_path_is_not_url(self):
        assert pipeline.is_url("video.mp4") is False


class TestDependencyCheck:
    def test_require_raises_when_missing(self):
        with pytest.raises(RuntimeError) as exc:
            pipeline._require("definitely-not-a-real-binary-xyz", "install it")
        assert "definitely-not-a-real-binary-xyz" in str(exc.value)

    def test_require_passes_for_python(self):
        # python3 should always be on PATH in the test environment.
        pipeline._require("python3", "install python")


class TestDownloadLocalFile:
    def test_missing_local_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            pipeline.download_video("/no/such/file.mp4", tmp_path, None)

    def test_existing_local_file_returned(self, tmp_path):
        fake = tmp_path / "clip.mp4"
        fake.write_bytes(b"not a real video")
        result = pipeline.download_video(str(fake), tmp_path, None)
        assert result == fake.resolve()


class TestFrameTimestamps:
    def test_frames_dataclass_roundtrip(self):
        frame = pipeline.Frame(path="/tmp/f.jpg", timestamp_seconds=4.0)
        assert frame.path == "/tmp/f.jpg"
        assert frame.timestamp_seconds == 4.0


class TestAppleSiliconDetection:
    def test_returns_bool(self):
        assert isinstance(pipeline.is_apple_silicon(), bool)


class TestHasAudioStream:
    def test_missing_file_has_no_audio(self, tmp_path):
        # A path that is not a real media file must not report an audio stream.
        fake = tmp_path / "nope.mp4"
        fake.write_bytes(b"not a video")
        assert pipeline.has_audio_stream(fake) is False


class TestExtractAudioNoStream:
    def test_extract_audio_returns_none_when_no_audio(self, tmp_path, monkeypatch):
        # When the video has no audio stream, extract_audio must return None
        # instead of raising, so the pipeline degrades to frames-only.
        monkeypatch.setattr(pipeline, "has_audio_stream", lambda _p: False)
        result = pipeline.extract_audio(tmp_path / "video.mp4", tmp_path)
        assert result is None


class TestTranscribeNoAudio:
    def test_transcribe_none_audio_returns_none_source(self):
        # Passing None audio (no stream) yields an empty transcript, source "none".
        text, source = pipeline.transcribe(None, "base")
        assert text == ""
        assert source == "none"
