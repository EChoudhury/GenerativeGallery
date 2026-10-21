"""
Gallery Grid Audio Server

Install:
    pip install fastapi uvicorn numpy soundfile scipy

Run:
    uvicorn server:app --host 192.168.125.250 --port 8000

Audio files:
    audio/cell_0_0.wav ... audio/cell_4_4.wav

API:
    POST /position
        {"x": 2.1, "y": 3.4}

    GET /audio
        Continuous raw PCM audio stream (stereo, 44.1 kHz, float32)

    GET /health
        Reports loaded and missing audio files.

Coordinates are in the range [0, 5].
The 5x5 cells are centered at (0.5, 0.5), (1.5, 0.5), etc.
Nearby cells are blended using inverse-distance weighting.
"""

from pathlib import Path
from threading import Lock
from typing import Generator

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, HTMLResponse
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------

GRID_SIZE = 5
SAMPLE_RATE = 44100
CHANNELS = 2
CHUNK_SECONDS = 0.1
CHUNK_SIZE = int(SAMPLE_RATE * CHUNK_SECONDS)

AUDIO_DIR = Path("audio")

# Higher values make the closest cell dominate more strongly.
DISTANCE_POWER = 2.0

# Prevents division by zero when a person is exactly at a cell center.
DISTANCE_EPSILON = 0.05

# A short smoothing time helps avoid sudden changes in audio level.
WEIGHT_SMOOTHING = 0.15


app = FastAPI(title="Gallery Grid Audio Server")


# ---------------------------------------------------------------------
# State
# ---------------------------------------------------------------------

class Position(BaseModel):
    x: float = Field(ge=0.0, le=5.0)
    y: float = Field(ge=0.0, le=5.0)


position_lock = Lock()
current_position = np.array([2.5, 2.5], dtype=np.float64)

audio_buffers: dict[tuple[int, int], np.ndarray] = {}
audio_lengths: dict[tuple[int, int], int] = {}
missing_files: list[str] = []


# ---------------------------------------------------------------------
# Audio loading
# ---------------------------------------------------------------------

def convert_to_stereo(audio: np.ndarray) -> np.ndarray:
    """Convert mono or multichannel audio into stereo."""
    if audio.ndim == 1:
        audio = np.column_stack((audio, audio))
    elif audio.shape[1] == 1:
        audio = np.repeat(audio, 2, axis=1)
    elif audio.shape[1] > 2:
        audio = audio[:, :2]

    return audio.astype(np.float32, copy=False)


def resample_audio(
    audio: np.ndarray,
    source_rate: int,
) -> np.ndarray:
    """Resample audio to the server's sample rate."""
    if source_rate == SAMPLE_RATE:
        return audio

    from math import gcd

    divisor = gcd(SAMPLE_RATE, source_rate)

    return resample_poly(
        audio,
        SAMPLE_RATE // divisor,
        source_rate // divisor,
        axis=0,
    ).astype(np.float32)


def load_audio_files() -> None:
    """Load all 25 grid-cell audio files into memory."""
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    for row in range(GRID_SIZE):
        for col in range(GRID_SIZE):
            key = (col, row)
            path = AUDIO_DIR / f"cell_{col}_{row}.wav"

            if not path.exists():
                missing_files.append(str(path))
                continue

            try:
                audio, source_rate = sf.read(
                    str(path),
                    dtype="float32",
                    always_2d=True,
                )

                audio = convert_to_stereo(audio)
                audio = resample_audio(audio, source_rate)

                if len(audio) == 0:
                    missing_files.append(f"{path} (empty file)")
                    continue

                audio_buffers[key] = audio
                audio_lengths[key] = len(audio)

                print(
                    f"Loaded {path}: "
                    f"{len(audio) / SAMPLE_RATE:.1f}s"
                )

            except Exception as exc:
                print(f"Could not load {path}: {exc}")
                missing_files.append(f"{path} (load error)")


@app.on_event("startup")
def startup() -> None:
    load_audio_files()


# ---------------------------------------------------------------------
# Position and blending
# ---------------------------------------------------------------------

def get_position() -> np.ndarray:
    with position_lock:
        return current_position.copy()


def calculate_weights(position: np.ndarray) -> dict:
    """
    Calculate the influence of each audio cell.

    Each cell is centered at (col + 0.5, row + 0.5).
    Nearby cells receive more weight; all weights sum to 1.
    """
    distances = {}

    for col, row in audio_buffers:
        center_x = col + 0.5
        center_y = row + 0.5

        dx = position[0] - center_x
        dy = position[1] - center_y

        distances[(col, row)] = np.sqrt(dx * dx + dy * dy)

    if not distances:
        return {}

    # Inverse-distance weighting.
    raw_weights = {
        key: 1.0 / (
            (distance + DISTANCE_EPSILON) ** DISTANCE_POWER
        )
        for key, distance in distances.items()
    }

    total = sum(raw_weights.values())

    if total <= 0:
        return {}

    return {
        key: weight / total
        for key, weight in raw_weights.items()
    }


# ---------------------------------------------------------------------
# Continuous audio generation
# ---------------------------------------------------------------------

def get_audio_chunk(
    playheads: dict[tuple[int, int], int],
    smoothed_weights: dict[tuple[int, int], float],
    target_weights: dict[tuple[int, int], float],
) -> np.ndarray:
    """
    Mix one chunk from the grid's audio files.

    Each audio file loops independently. Its playhead advances
    continuously, even as the listener moves between cells.
    """
    output = np.zeros((CHUNK_SIZE, CHANNELS), dtype=np.float32)

    # Smooth the weights to avoid abrupt transitions.
    for key in audio_buffers:
        previous = smoothed_weights.get(key, 0.0)
        target = target_weights.get(key, 0.0)

        smoothed_weights[key] = (
            previous
            + WEIGHT_SMOOTHING * (target - previous)
        )

    # Renormalize to preserve a stable overall gain.
    weight_sum = sum(smoothed_weights.values())

    if weight_sum > 0:
        for key in smoothed_weights:
            smoothed_weights[key] /= weight_sum

    for key, audio in audio_buffers.items():
        weight = smoothed_weights.get(key, 0.0)

        if weight < 0.0001:
            continue

        audio_length = audio_lengths[key]
        start = playheads.get(key, 0)

        # Read a chunk, wrapping around the end of the file.
        indices = (start + np.arange(CHUNK_SIZE)) % audio_length
        chunk = audio[indices]

        output += chunk * weight

        playheads[key] = (start + CHUNK_SIZE) % audio_length

    # Keep the output within a safe floating-point range.
    # Soft clipping avoids harsh distortion if several layers overlap.
    output = np.tanh(output * 0.9).astype(np.float32)

    return output


def audio_stream() -> Generator[bytes, None, None]:
    """
    Yield continuous stereo float32 PCM chunks.

    The client must interpret this as raw PCM:
        sample rate: 44100 Hz
        channels: 2
        format: float32 little-endian
    """
    playheads = {
        key: 0
        for key in audio_buffers
    }

    smoothed_weights = {
        key: 0.0
        for key in audio_buffers
    }

    target_weights = calculate_weights(get_position())

    while True:
        position = get_position()
        target_weights = calculate_weights(position)

        chunk = get_audio_chunk(
            playheads,
            smoothed_weights,
            target_weights,
        )

        # Explicitly use little-endian float32.
        yield chunk.astype("<f4", copy=False).tobytes()


# ---------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------

@app.post("/position")
def update_position(position: Position) -> dict:
    """Update the listener's current position in the room."""
    global current_position

    with position_lock:
        current_position = np.array(
            [position.x, position.y],
            dtype=np.float64,
        )

    return {
        "status": "ok",
        "position": {
            "x": position.x,
            "y": position.y,
        },
    }


@app.get("/audio")
def stream_audio() -> StreamingResponse:
    """
    Stream continuous raw PCM audio.

    This is not a WAV file: it has no file header because the stream
    is intended to remain open indefinitely.
    """
    if not audio_buffers:
        raise HTTPException(
            status_code=503,
            detail=(
                "No audio files are loaded. Add WAV files to the "
                "'audio' directory and restart the server."
            ),
        )

    return StreamingResponse(
        audio_stream(),
        media_type="application/octet-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "X-Audio-Sample-Rate": str(SAMPLE_RATE),
            "X-Audio-Channels": str(CHANNELS),
            "X-Audio-Format": "float32-le",
        },
    )


@app.get("/health")
def health() -> dict:
    """Check which grid audio files loaded successfully."""
    return {
        "status": "ok" if audio_buffers else "no_audio",
        "loaded_cells": len(audio_buffers),
        "missing_files": missing_files,
        "sample_rate": SAMPLE_RATE,
        "channels": CHANNELS,
        "position": get_position().tolist(),
    }


@app.get("/")
def home() -> HTMLResponse:
    """Serve a simple test page with a position slider."""
    return HTMLResponse(
        """
<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <title>Gallery Audio Grid</title>
    <style>
        body {
            font-family: sans-serif;
            max-width: 650px;
            margin: 40px auto;
            padding: 0 20px;
        }
        .control { margin: 24px 0; }
        input { width: 100%; }
        button { padding: 10px 16px; }
        #grid {
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            gap: 5px;
            margin-top: 20px;
        }
        .cell {
            background: #eee;
            padding: 20px 5px;
            text-align: center;
            border-radius: 5px;
        }
        .active { background: #a7d8ff; }
    </style>
</head>
<body>
    <h1>Gallery Audio Grid</h1>
    <p>Move around the grid to blend the audio layers.</p>

    <button id="start">Start audio stream</button>

    <div class="control">
        <label for="x">X position: <span id="xvalue">2.5</span></label>
        <input id="x" type="range" min="0" max="5"
               step="0.05" value="2.5">
    </div>

    <div class="control">
        <label for="y">Y position: <span id="yvalue">2.5</span></label>
        <input id="y" type="range" min="0" max="5"
               step="0.05" value="2.5">
    </div>

    <div id="status">Audio is stopped.</div>
    <div id="grid"></div>

    <script>
        const xSlider = document.getElementById("x");
        const ySlider = document.getElementById("y");
        const grid = document.getElementById("grid");
        const status = document.getElementById("status");

        for (let row = 4; row >= 0; row--) {
            for (let col = 0; col < 5; col++) {
                const cell = document.createElement("div");
                cell.className = "cell";
                cell.id = `cell-${col}-${row}`;
                cell.textContent = `${col}, ${row}`;
                grid.appendChild(cell);
            }
        }

        async function sendPosition() {
            const x = Number(xSlider.value);
            const y = Number(ySlider.value);

            document.getElementById("xvalue").textContent = x.toFixed(2);
            document.getElementById("yvalue").textContent = y.toFixed(2);

            await fetch("/position", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({x, y})
            });

            document.querySelectorAll(".cell").forEach(el => {
                el.classList.remove("active");
            });

            const col = Math.min(4, Math.floor(x));
            const row = Math.min(4, Math.floor(y));
            document.getElementById(`cell-${col}-${row}`)
                .classList.add("active");
        }

        xSlider.addEventListener("input", sendPosition);
        ySlider.addEventListener("input", sendPosition);

        document.getElementById("start").addEventListener("click", () => {
            status.textContent =
                "The raw PCM endpoint is /audio. A PCM-capable audio client is required.";
            window.open("/audio", "_blank");
        });

        sendPosition();
    </script>
</body>
</html>
        """
    )