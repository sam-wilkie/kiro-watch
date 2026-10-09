#!/usr/bin/env python3
"""
kiro-watch: give the Kiro agent eyes and ears for any video.

This script is the "perception layer". It does NOT interpret the video.
It downloads a video (yt-dlp), extracts frames (ffmpeg), and transcribes
the audio locally (mlx-whisper on Apple Silicon, openai-whisper on CPU).
It then prints a JSON manifest of frame paths + transcript so the host
agent (Kiro) can read the frames as images and the transcript as text.

No API keys. Nothing leaves the machine except the original video download.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path

# --- Constants ---------------------------------------------------------------

DEFAULT_FPS = 0.5  # one frame every 2 seconds
DEFAULT_MAX_FRAMES = 60
FRAME_WIDTH = 768  # downscale frames to keep them light for the vision model


# --- Data types --------------------------------------------------------------


@dataclass
class Frame:
    path: str
    timestamp_seconds: float


@dataclass
class WatchResult:
    source: str
    local_video_path: str
    duration_seconds: float
    frames: list[Frame]
    transcript: str
    transcript_source: str  # "captions" | "whisper" | "none"
    output_dir: str


# --- Dependency checks -------------------------------------------------------


def _require(binary: str, install_hint: str) -> None:
    if shutil.which(binary) is None:
        raise RuntimeError(
            f"Required dependency '{binary}' not found. Install it: {install_hint}"
        )


def check_dependencies() -> None:
    _require("ffmpeg", "brew install ffmpeg")
    _require("yt-dlp", "brew install yt-dlp  (or: pip install yt-dlp)")


# --- Download ----------------------------------------------------------------


def is_url(source: str) -> bool:
    return bool(re.match(r"^https?://", source))


def download_video(source: str, work_dir: Path, cookies_from_browser: str | None) -> Path:
    """Download a remote video with yt-dlp, or return the local path as-is."""
    if not is_url(source):
        local = Path(source).expanduser().resolve()
        if not local.exists():
            raise FileNotFoundError(f"Local video not found: {local}")
        return local

    out_template = str(work_dir / "video.%(ext)s")
    cmd = [
        "yt-dlp",
        "-f",
        "mp4/best",
        "--no-playlist",
        "-o",
        out_template,
    ]
    if cookies_from_browser:
        cmd += ["--cookies-from-browser", cookies_from_browser]
    cmd.append(source)

    subprocess.run(cmd, check=True)

    candidates = sorted(work_dir.glob("video.*"))
    videos = [c for c in candidates if c.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}]
    if not videos:
        raise RuntimeError("yt-dlp did not produce a video file")
    return videos[0]


# --- Probe -------------------------------------------------------------------


def probe_duration(video_path: Path) -> float:
    try:
        out = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        return float(out.stdout.strip())
    except Exception:
        return 0.0


# --- Frames ------------------------------------------------------------------


def extract_frames(
    video_path: Path, out_dir: Path, fps: float, max_frames: int
) -> list[Frame]:
    frames_dir = out_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    pattern = str(frames_dir / "frame_%04d.jpg")
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video_path),
        "-vf",
        f"fps={fps},scale={FRAME_WIDTH}:-1",
        "-frames:v",
        str(max_frames),
        pattern,
    ]
    subprocess.run(cmd, check=True)

    frames: list[Frame] = []
    interval = 1.0 / fps if fps > 0 else 0.0
    for i, frame_path in enumerate(sorted(frames_dir.glob("frame_*.jpg"))):
        frames.append(Frame(path=str(frame_path), timestamp_seconds=round(i * interval, 2)))
    return frames


# --- Transcript --------------------------------------------------------------


def extract_audio(video_path: Path, out_dir: Path) -> Path:
    audio_path = out_dir / "audio.wav"
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(video_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        str(audio_path),
    ]
    subprocess.run(cmd, check=True)
    return audio_path


def is_apple_silicon() -> bool:
    return platform.system() == "Darwin" and platform.machine() == "arm64"


def transcribe(audio_path: Path, model: str) -> tuple[str, str]:
    """Return (transcript_text, engine). Tries mlx-whisper then openai-whisper."""
    # Try mlx-whisper (Apple Silicon, Neural Engine)
    if is_apple_silicon():
        try:
            import mlx_whisper  # type: ignore

            result = mlx_whisper.transcribe(
                str(audio_path),
                path_or_hf_repo=f"mlx-community/whisper-{model}",
            )
            return result.get("text", "").strip(), "mlx-whisper"
        except ImportError:
            pass
        except Exception as exc:  # pragma: no cover - runtime engine failure
            print(f"[kiro-watch] mlx-whisper failed: {exc}", file=sys.stderr)

    # Fallback: openai-whisper (CPU)
    try:
        import whisper  # type: ignore

        wmodel = whisper.load_model(model)
        result = wmodel.transcribe(str(audio_path))
        return result.get("text", "").strip(), "openai-whisper"
    except ImportError:
        return "", "none"
    except Exception as exc:  # pragma: no cover - runtime engine failure
        print(f"[kiro-watch] openai-whisper failed: {exc}", file=sys.stderr)
        return "", "none"


# --- Orchestration -----------------------------------------------------------


def watch(
    source: str,
    output_dir: Path,
    fps: float,
    max_frames: int,
    model: str,
    cookies_from_browser: str | None,
    skip_transcript: bool,
) -> WatchResult:
    check_dependencies()
    output_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        video_path = download_video(source, tmp_dir, cookies_from_browser)

        # Persist a copy of the video next to the frames for reference.
        persisted_video = output_dir / f"video{video_path.suffix}"
        shutil.copy2(video_path, persisted_video)

        duration = probe_duration(persisted_video)
        frames = extract_frames(persisted_video, output_dir, fps, max_frames)

        transcript, transcript_source = "", "none"
        if not skip_transcript:
            audio_path = extract_audio(persisted_video, output_dir)
            transcript, transcript_source = transcribe(audio_path, model)
            # Clean up the large wav; we only needed the text.
            audio_path.unlink(missing_ok=True)

    return WatchResult(
        source=source,
        local_video_path=str(persisted_video),
        duration_seconds=round(duration, 2),
        frames=frames,
        transcript=transcript,
        transcript_source=transcript_source,
        output_dir=str(output_dir),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="kiro-watch: extract frames + transcript so Kiro can watch a video."
    )
    parser.add_argument("source", help="Video URL (yt-dlp supported) or local file path")
    parser.add_argument(
        "-o",
        "--output-dir",
        default=None,
        help="Where to write frames/transcript (default: ./.kiro-watch/<slug>)",
    )
    parser.add_argument(
        "--fps",
        type=float,
        default=DEFAULT_FPS,
        help=f"Frames per second to sample (default: {DEFAULT_FPS})",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=DEFAULT_MAX_FRAMES,
        help=f"Maximum number of frames (default: {DEFAULT_MAX_FRAMES})",
    )
    parser.add_argument(
        "--model",
        default="base",
        help="Whisper model size: tiny|base|small|medium|large (default: base)",
    )
    parser.add_argument(
        "--cookies-from-browser",
        default=None,
        help="Browser to read cookies from for login-gated sources (e.g. chrome, safari)",
    )
    parser.add_argument(
        "--skip-transcript",
        action="store_true",
        help="Only extract frames, skip audio transcription",
    )
    args = parser.parse_args(argv)

    if args.output_dir:
        output_dir = Path(args.output_dir).expanduser().resolve()
    else:
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", args.source)[-40:].strip("-") or "video"
        output_dir = Path.cwd() / ".kiro-watch" / slug

    try:
        result = watch(
            source=args.source,
            output_dir=output_dir,
            fps=args.fps,
            max_frames=args.max_frames,
            model=args.model,
            cookies_from_browser=args.cookies_from_browser,
            skip_transcript=args.skip_transcript,
        )
    except Exception as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1

    print(json.dumps(asdict(result), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
