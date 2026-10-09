#!/usr/bin/env python3
"""
kiro-watch setup: install the perception-layer dependencies.

Mechanical only. Installs ffmpeg + yt-dlp (via Homebrew on macOS) and a local
Whisper engine (mlx-whisper on Apple Silicon, openai-whisper elsewhere).
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys


def have(binary: str) -> bool:
    return shutil.which(binary) is not None


def run(cmd: list[str]) -> None:
    print(f"[setup] $ {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def ensure_system_deps() -> None:
    system = platform.system()
    missing = [b for b in ("ffmpeg", "yt-dlp") if not have(b)]
    if not missing:
        print("[setup] ffmpeg + yt-dlp already present.")
        return

    if system == "Darwin" and have("brew"):
        run(["brew", "install", *missing])
    else:
        print(
            "[setup] Please install manually: "
            + ", ".join(missing)
            + "\n  macOS:  brew install " + " ".join(missing)
            + "\n  Linux:  sudo apt install ffmpeg  &&  pip install yt-dlp"
            + "\n  Windows: winget install ffmpeg  &&  pip install yt-dlp"
        )


def ensure_whisper() -> None:
    is_apple_silicon = platform.system() == "Darwin" and platform.machine() == "arm64"
    pkg = "mlx-whisper" if is_apple_silicon else "openai-whisper"
    print(f"[setup] Installing local Whisper engine: {pkg}")
    try:
        run([sys.executable, "-m", "pip", "install", pkg])
    except subprocess.CalledProcessError:
        print(f"[setup] WARNING: failed to install {pkg}. Transcription will be unavailable.")


def main() -> int:
    print("[setup] kiro-watch dependency setup")
    ensure_system_deps()
    ensure_whisper()
    print("[setup] Done. Try: python3 scripts/watch.py <video-url-or-path>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
