# kiro-watch

**Give the Kiro agent eyes and ears for any video — 100% local, no API key.**

Paste a video URL (YouTube, Vimeo, TikTok, X/Twitter, Instagram, Loom, and
~1800 more via [yt-dlp](https://github.com/yt-dlp/yt-dlp)) or a local file, and
`kiro-watch` downloads it, extracts frames as images, and transcribes the audio
locally with Whisper. It then hands Kiro the frame paths and the transcript so
Kiro reads the frames with its **own** vision and answers questions about the
video.

## Why this exists

Kiro can read images natively but has no video input. Most "watch a video"
tools send the whole file to a paid multimodal API. `kiro-watch` doesn't — it's
a **perception layer**, not an interpretation layer:

```
video → [yt-dlp] download → [ffmpeg] frames + audio → [whisper] transcript
      → Kiro reads frames (its own vision) + transcript → answer
```

The model that "watches" the video is Kiro itself. Nothing leaves your machine
except the original video download. No API key, no cloud inference, no fees.

## Requirements

- **Python 3.9+**
- **ffmpeg** and **yt-dlp** (auto-installed on macOS via Homebrew by the setup script)
- A local Whisper engine (only needed for transcription):
  - **mlx-whisper** — Apple Silicon, runs on the Neural Engine (preferred on M-series)
  - **openai-whisper** — CPU fallback (Intel/Linux/Windows)

## Install

```bash
git clone https://github.com/<you>/kiro-watch.git
cd kiro-watch
python3 scripts/setup.py   # installs ffmpeg, yt-dlp, and the right Whisper engine
```

## Use it with Kiro (MCP)

Register the MCP server globally:

```bash
kiro-cli mcp add \
  --name kiro-watch \
  --command python3 \
  --args "$(pwd)/scripts/mcp_server.py" \
  --scope global
```

Or add it by hand to `~/.kiro/settings/mcp.json`:

```json
{
  "mcpServers": {
    "kiro-watch": {
      "command": "python3",
      "args": ["/absolute/path/to/kiro-watch/scripts/mcp_server.py"]
    }
  }
}
```

Then just ask Kiro:

> watch this video and tell me what happens at 0:30 — https://youtu.be/dQw4w9WgXcQ

Kiro calls the `watch_video` tool, reads the returned frames with its vision,
and answers.

## Use it standalone (CLI)

```bash
python3 scripts/watch.py "https://youtu.be/dQw4w9WgXcQ"
python3 scripts/watch.py ./local-clip.mp4 --fps 1 --max-frames 40
python3 scripts/watch.py "<url>" --skip-transcript        # frames only
python3 scripts/watch.py "<url>" --cookies-from-browser chrome   # login-gated
```

Output goes to `./.kiro-watch/<slug>/` with a `frames/` folder and a JSON
manifest printed to stdout.

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--fps` | `0.5` | Frames per second to sample (0.5 = one frame every 2s) |
| `--max-frames` | `60` | Cap on number of frames |
| `--model` | `base` | Whisper size: `tiny`\|`base`\|`small`\|`medium`\|`large` |
| `--cookies-from-browser` | — | Read cookies for login-gated videos (`chrome`, `safari`, …) |
| `--skip-transcript` | off | Only extract frames |
| `-o`, `--output-dir` | `./.kiro-watch/<slug>` | Where to write output |

## How transcription stays local

On Apple Silicon the setup installs `mlx-whisper`, which runs on-device via the
Neural Engine. Everywhere else it installs `openai-whisper` (CPU). The audio is
extracted to a temporary 16kHz mono WAV, transcribed, and the WAV is deleted —
only the text is kept.

## Tests

```bash
python3 -m pytest tests/ -v
```

## License

MIT — see [LICENSE](LICENSE). Built for the Kiro community.
