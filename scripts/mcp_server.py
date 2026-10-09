#!/usr/bin/env python3
"""
kiro-watch MCP server (stdio).

Exposes one tool, `watch_video`, that runs the perception pipeline and returns
a manifest the host agent can act on: the list of frame image paths (to read
with its own vision) and the local transcript text.

The server deliberately does NOT interpret the video. Interpretation is the
host agent's job — this server only gives it eyes and ears.

Protocol: minimal JSON-RPC 2.0 over stdio, implementing the subset of MCP that
Kiro needs: initialize, tools/list, tools/call.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow importing the sibling pipeline module.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import watch as pipeline  # noqa: E402

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "kiro-watch"
SERVER_VERSION = "0.1.0"

TOOLS = [
    {
        "name": "watch_video",
        "description": (
            "Give the agent eyes and ears for a video. Downloads a video "
            "(any yt-dlp supported site, or a local file), extracts sampled "
            "frames as JPEG images, and transcribes the audio locally with "
            "Whisper (no API key, nothing leaves the machine). Returns the "
            "frame image paths and the transcript so you can read the frames "
            "with your own vision and answer questions about the video."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Video URL or local file path.",
                },
                "fps": {
                    "type": "number",
                    "description": "Frames per second to sample (default 0.5 = one frame every 2s).",
                },
                "max_frames": {
                    "type": "integer",
                    "description": "Maximum number of frames to extract (default 60).",
                },
                "model": {
                    "type": "string",
                    "description": "Whisper model size: tiny|base|small|medium|large (default base).",
                },
                "cookies_from_browser": {
                    "type": "string",
                    "description": "Browser to read cookies from for login-gated videos (e.g. chrome, safari).",
                },
                "skip_transcript": {
                    "type": "boolean",
                    "description": "Only extract frames, skip transcription.",
                },
            },
            "required": ["source"],
        },
    }
]


def _result(request_id, result):
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id, code, message):
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def handle_initialize(request_id, _params):
    return _result(
        request_id,
        {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        },
    )


def handle_tools_list(request_id, _params):
    return _result(request_id, {"tools": TOOLS})


def handle_tools_call(request_id, params):
    name = params.get("name")
    if name != "watch_video":
        return _error(request_id, -32602, f"Unknown tool: {name}")

    args = params.get("arguments", {})
    source = args.get("source")
    if not source:
        return _error(request_id, -32602, "Missing required argument: source")

    slug = pipeline.re.sub(r"[^a-zA-Z0-9]+", "-", source)[-40:].strip("-") or "video"
    output_dir = Path.cwd() / ".kiro-watch" / slug

    try:
        res = pipeline.watch(
            source=source,
            output_dir=output_dir,
            fps=float(args.get("fps", pipeline.DEFAULT_FPS)),
            max_frames=int(args.get("max_frames", pipeline.DEFAULT_MAX_FRAMES)),
            model=str(args.get("model", "base")),
            cookies_from_browser=args.get("cookies_from_browser"),
            skip_transcript=bool(args.get("skip_transcript", False)),
        )
    except Exception as exc:
        return _result(
            request_id,
            {
                "content": [{"type": "text", "text": f"kiro-watch error: {exc}"}],
                "isError": True,
            },
        )

    manifest = {
        "source": res.source,
        "duration_seconds": res.duration_seconds,
        "transcript_source": res.transcript_source,
        "transcript": res.transcript,
        "frame_count": len(res.frames),
        "frames": [{"path": f.path, "t": f.timestamp_seconds} for f in res.frames],
        "output_dir": res.output_dir,
    }

    summary = (
        f"Watched: {res.source}\n"
        f"Duration: {res.duration_seconds}s | Frames: {len(res.frames)} "
        f"(in {res.output_dir}/frames) | Transcript: {res.transcript_source}\n\n"
        f"Next: read the frame images listed below with your Image reader to "
        f"see the video, and use the transcript for the audio.\n\n"
        f"--- MANIFEST ---\n{json.dumps(manifest, indent=2)}"
    )

    return _result(
        request_id,
        {"content": [{"type": "text", "text": summary}], "isError": False},
    )


HANDLERS = {
    "initialize": handle_initialize,
    "tools/list": handle_tools_list,
    "tools/call": handle_tools_call,
}


def serve() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = message.get("method")
        request_id = message.get("id")

        # Notifications (no id) that need no response.
        if method is not None and request_id is None:
            continue

        handler = HANDLERS.get(method)
        if handler is None:
            response = _error(request_id, -32601, f"Method not found: {method}")
        else:
            try:
                response = handler(request_id, message.get("params", {}))
            except Exception as exc:  # pragma: no cover
                response = _error(request_id, -32603, f"Internal error: {exc}")

        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    serve()
