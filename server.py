
"""
server.py

Gallery Grid Audio Server:
- Two-beacon BLE positioning along a 1D gallery.
- Five audio cells with browser-side Web Audio crossfading.
- Independent continuous drone.
- Background Stability AI generation from two emotional endpoints.
- Publishes each generated cell as soon as it is ready.
- Live browser crossfade when the currently playing cell is updated.
- Four Raspberry Pi GPIO buttons for live emotion parameter control.
- Automatically generates a new soundscape when intensity_a remains
  unchanged for five seconds.
- Queues subsequent automatic generation if intensity changes during a job.

Install:
    pip install fastapi uvicorn bleak requests python-dotenv gpiozero

Run:
    uvicorn server:app --host 0.0.0.0 --port 8000

Environment:
    STABILITY_API_KEY=your_api_key
    BEACON_A_ADDRESS=AA:BB:CC:DD:EE:01
    BEACON_B_ADDRESS=AA:BB:CC:DD:EE:02
"""

import asyncio
import math
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

from bleak import BleakScanner
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field
from gpiozero import Button

from generate_assets import StabilityAudioClient, build_emotion_prompt

load_dotenv()

app = FastAPI(title="Gallery Grid Audio Server")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GRID_SIZE = 5
GRID_MAX_X = 5.0

AUDIO_DIR = Path("audio")
GENERATED_DIR = AUDIO_DIR / "generated"

BEACON_A_ADDRESS = os.getenv("BEACON_A_ADDRESS", "").strip().lower()
BEACON_B_ADDRESS = os.getenv("BEACON_B_ADDRESS", "").strip().lower()

GENERATION_DURATION_SECONDS = 30
GENERATION_STRENGTH = 0.80

# Automatically generate after intensity_a has stopped changing for this long.
INTENSITY_STABILITY_SECONDS = 5.0
INTENSITY_WATCH_INTERVAL_SECONDS = 0.25

RSSI_SMOOTHING_ALPHA = 0.25
POSITION_SMOOTHING_ALPHA = 0.25
BLE_SCAN_INTERVAL_SECONDS = 0.5

BASE_SOUND_PROMPT = (
    "A calming, immersive ambient soundscape for a contemporary art gallery. "
    "A continuous tonal foundation with evolving organic textures, subtle "
    "rhythmic detail, spatial depth, and a coherent musical identity. "
    "No vocals. No abrupt cuts."
)

# BCM GPIO numbering.
# GPIO 27 is physical pin 13, NOT physical pin 27.
GPIO_BUTTON_PINS = {
    1: 17,  # Physical pin 11: intensity_a = 1.0
    2: 27,  # Physical pin 13: intensity_a = 0.0
    3: 22,  # Physical pin 15: valence_a = 1.0
    4: 23,  # Physical pin 16: valence_a = 0.0
}

GPIO_BOUNCE_TIME = 0.15


# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------

state_lock = threading.RLock()

current_position = {"x": 0.0, "y": 0.0}
position_source = "ble"
position_mode = "automatic"

beacon_rssi = {
    "a": None,
    "b": None,
}

ble_status = {
    "running": False,
    "message": "BLE scanner has not started.",
    "last_update": None,
}

gpio_status = {
    "available": False,
    "message": "GPIO buttons have not been initialized.",
    "last_button": None,
    "last_update": None,
}

gpio_buttons = {}

smoothed_position_x = 0.0
current_column = 0

current_emotion_parameters = {
    "intensity_a": 0.5,
    "valence_a": 0.0,
    "intensity_b": 0.5,
    "valence_b": 0.0,
}

audio_versions = {
    "original": {
        col: AUDIO_DIR / f"cell_{col}.mp3"
        for col in range(GRID_SIZE)
    }
}

active_audio_version = "original"

published_cells = {
    col: {
        "version": "original",
        "url": f"/audio/{col}?version=original",
        "updated_at": None,
    }
    for col in range(GRID_SIZE)
}

generation_state = {
    "status": "idle",
    "job_id": None,
    "progress": 0,
    "total": GRID_SIZE,
    "current_column": None,
    "message": "No generation requested yet.",
    "error": None,
    "started_at": None,
    "finished_at": None,
    "parameters": None,
}

ble_task: Optional[asyncio.Task] = None
generation_task: Optional[asyncio.Task] = None
intensity_watch_task: Optional[asyncio.Task] = None

# Monotonic timestamps are unaffected by system clock adjustments.
# None means intensity_a has not changed since the server started.
intensity_change_at: Optional[float] = None

# Timestamp of the most recent intensity change already handled by
# an automatic or manual generation request.
last_auto_triggered_change_at: Optional[float] = None


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class PositionUpdate(BaseModel):
    x: float = Field(ge=0.0, le=GRID_MAX_X)
    y: float = Field(default=0.0, ge=0.0, le=5.0)


class ModeUpdate(BaseModel):
    mode: str


class EmotionParameters(BaseModel):
    intensity_a: float = Field(ge=0.0, le=1.0)
    valence_a: float = Field(ge=-1.0, le=1.0)
    intensity_b: float = Field(ge=0.0, le=1.0)
    valence_b: float = Field(ge=-1.0, le=1.0)


# ---------------------------------------------------------------------------
# Emotion parameter tracking
# ---------------------------------------------------------------------------

def update_emotion_parameters(values: dict) -> bool:
    """
    Update one or more emotion parameters.

    If intensity_a actually changes, restart the five-second stability timer.

    Partial dictionaries are allowed, which is useful for GPIO buttons.
    Returns True if intensity_a changed.
    """
    global intensity_change_at

    with state_lock:
        old_intensity = current_emotion_parameters["intensity_a"]

        current_emotion_parameters.update(values)

        new_intensity = current_emotion_parameters["intensity_a"]
        intensity_changed = abs(new_intensity - old_intensity) > 1e-9

        if intensity_changed:
            intensity_change_at = time.monotonic()

            print(
                f"[AUTO-GENERATION] intensity_a changed "
                f"{old_intensity:.2f} -> {new_intensity:.2f}. "
                f"Waiting {INTENSITY_STABILITY_SECONDS:.0f}s for stability."
            )

        return intensity_changed


# ---------------------------------------------------------------------------
# GPIO emotion controls
# ---------------------------------------------------------------------------

def handle_gpio_button(button_number: int):
    """
    Update emotion parameters when a physical GPIO button is pressed.

    Button 1: intensity_a = 1.0
    Button 2: intensity_a = 0.0
    Button 3: valence_a = 1.0
    Button 4: valence_a = 0.0

    Only the specified parameter changes.
    Intensity changes start or restart the automatic-generation timer.
    """
    updates = {
        1: {"intensity_a": 1.0},
        2: {"intensity_a": 0.0},
        3: {"valence_a": 1.0},
        4: {"valence_a": 0.0},
    }

    if button_number not in updates:
        return

    changed = update_emotion_parameters(updates[button_number])

    with state_lock:
        gpio_status["last_button"] = button_number
        gpio_status["last_update"] = time.time()
        gpio_status["message"] = (
            f"Button {button_number} pressed. "
            f"Updated: {updates[button_number]}"
        )

        parameters = dict(current_emotion_parameters)

    print(
        f"[GPIO] Button {button_number} pressed | "
        f"Emotion parameters: {parameters}"
    )

    if button_number in (1, 2) and not changed:
        print(
            "[GPIO] Intensity was already at the requested value; "
            "the stability timer was not restarted."
        )


def initialize_gpio_buttons():
    """
    Initialize all four physical buttons.

    Uses BCM GPIO numbering and internal pull-up resistors.
    Each normally open button connects its GPIO pin to GND when pressed.

    If GPIO initialization fails, the server continues running without
    physical button controls.
    """
    global gpio_buttons

    try:
        for button_number, pin in GPIO_BUTTON_PINS.items():
            button = Button(
                pin,
                pull_up=True,
                bounce_time=GPIO_BOUNCE_TIME,
            )

            button.when_pressed = (
                lambda number=button_number:
                handle_gpio_button(number)
            )

            gpio_buttons[button_number] = button

            print(
                f"[GPIO] Button {button_number} initialized: "
                f"BCM GPIO {pin}"
            )

        with state_lock:
            gpio_status["available"] = True
            gpio_status["message"] = (
                "All four GPIO buttons initialized successfully."
            )

        print("[GPIO] All four emotion buttons initialized.")

    except Exception as exc:
        for button in gpio_buttons.values():
            button.close()

        gpio_buttons.clear()

        with state_lock:
            gpio_status["available"] = False
            gpio_status["message"] = (
                f"GPIO initialization failed: {exc}"
            )

        print(f"[GPIO] Initialization failed: {exc}")
        print("[GPIO] Server will continue without physical buttons.")


# ---------------------------------------------------------------------------
# Positioning
# ---------------------------------------------------------------------------

def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def x_to_column(x: float) -> int:
    """Map x in [0, 5] to one of five cells."""
    return min(GRID_SIZE - 1, max(0, int(round(x))))


def estimate_x_from_rssi(
    rssi_a: Optional[float],
    rssi_b: Optional[float],
) -> Optional[float]:
    """
    Estimate position between two beacons.

    A stronger beacon A signal places the visitor closer to x=0.
    A stronger beacon B signal places the visitor closer to x=5.
    """
    if rssi_a is None and rssi_b is None:
        return None

    if rssi_a is None:
        return GRID_MAX_X

    if rssi_b is None:
        return 0.0

    difference = rssi_a - rssi_b

    fraction_toward_b = 1.0 / (
        1.0 + math.exp(clamp(difference / 8.0, -20, 20))
    )

    return fraction_toward_b * GRID_MAX_X


def update_position_from_rssi():
    global smoothed_position_x, current_column

    with state_lock:
        raw_x = estimate_x_from_rssi(
            beacon_rssi["a"],
            beacon_rssi["b"],
        )

        if raw_x is None:
            return

        smoothed_position_x = (
            POSITION_SMOOTHING_ALPHA * raw_x
            + (1.0 - POSITION_SMOOTHING_ALPHA) * smoothed_position_x
        )

        current_position["x"] = clamp(
            smoothed_position_x,
            0.0,
            GRID_MAX_X,
        )
        current_position["y"] = 0.0

        current_column = x_to_column(current_position["x"])
        ble_status["last_update"] = time.time()


def normalize_address(address: str) -> str:
    return address.strip().lower()


async def ble_scanner_loop():
    """Continuously scan for the two configured BLE beacons."""
    global beacon_rssi

    if not BEACON_A_ADDRESS or not BEACON_B_ADDRESS:
        with state_lock:
            ble_status["running"] = False
            ble_status["message"] = (
                "Set BEACON_A_ADDRESS and BEACON_B_ADDRESS to enable BLE."
            )
        return

    with state_lock:
        ble_status["running"] = True
        ble_status["message"] = "Scanning for configured beacons."

    try:
        while True:
            try:
                discovered = await BleakScanner.discover(
                    timeout=1.0,
                    return_adv=True,
                )

                for address, result in discovered.items():
                    device, advertisement = result
                    normalized = normalize_address(address)

                    rssi = getattr(advertisement, "rssi", None)

                    if rssi is None:
                        rssi = getattr(device, "rssi", None)

                    if rssi is None:
                        continue

                    with state_lock:
                        if normalized == BEACON_A_ADDRESS:
                            old = beacon_rssi["a"]

                            beacon_rssi["a"] = (
                                float(rssi)
                                if old is None
                                else RSSI_SMOOTHING_ALPHA * float(rssi)
                                + (1.0 - RSSI_SMOOTHING_ALPHA) * old
                            )

                        elif normalized == BEACON_B_ADDRESS:
                            old = beacon_rssi["b"]

                            beacon_rssi["b"] = (
                                float(rssi)
                                if old is None
                                else RSSI_SMOOTHING_ALPHA * float(rssi)
                                + (1.0 - RSSI_SMOOTHING_ALPHA) * old
                            )

                with state_lock:
                    automatic = position_mode == "automatic"

                if automatic:
                    update_position_from_rssi()

            except asyncio.CancelledError:
                raise

            except Exception as exc:
                with state_lock:
                    ble_status["message"] = f"BLE scan error: {exc}"

            await asyncio.sleep(BLE_SCAN_INTERVAL_SECONDS)

    except asyncio.CancelledError:
        pass

    finally:
        with state_lock:
            ble_status["running"] = False
            ble_status["message"] = "BLE scanner stopped."


# ---------------------------------------------------------------------------
# Emotion-to-prompt mapping and generation
# ---------------------------------------------------------------------------

def interpolate_emotions(params: dict, column: int):
    """Interpolate intensity and valence from beacon A to beacon B."""
    t = column / max(1, GRID_SIZE - 1)

    intensity = (
        params["intensity_a"] * (1.0 - t)
        + params["intensity_b"] * t
    )

    valence = (
        params["valence_a"] * (1.0 - t)
        + params["valence_b"] * t
    )

    return intensity, valence


def set_generation_state(**updates):
    with state_lock:
        generation_state.update(updates)


async def watch_intensity_stability():
    """
    Automatically generate a soundscape after intensity_a remains unchanged
    for INTENSITY_STABILITY_SECONDS.

    If a generation is already running, leave the new intensity change
    pending. The watcher checks again after the current job finishes.
    """
    global generation_task
    global last_auto_triggered_change_at

    while True:
        try:
            await asyncio.sleep(INTENSITY_WATCH_INTERVAL_SECONDS)

            with state_lock:
                changed_at = intensity_change_at

                if changed_at is None:
                    continue

                # No new intensity change since the last automatic or manual
                # generation handled this change.
                if changed_at == last_auto_triggered_change_at:
                    continue

                stable_for = time.monotonic() - changed_at

                if stable_for < INTENSITY_STABILITY_SECONDS:
                    continue

                if generation_state["status"] in ("queued", "running"):
                    # Keep the latest change pending.
                    continue

                # Capture the latest emotion parameters when the timer expires.
                params = dict(current_emotion_parameters)
                job_id = uuid.uuid4().hex[:12]

                audio_versions[job_id] = {}

                generation_state.update({
                    "status": "queued",
                    "job_id": job_id,
                    "progress": 0,
                    "total": GRID_SIZE,
                    "current_column": None,
                    "message": (
                        "Intensity remained stable for "
                        f"{INTENSITY_STABILITY_SECONDS:.0f} seconds. "
                        "Automatically generating a new soundscape."
                    ),
                    "error": None,
                    "started_at": None,
                    "finished_at": None,
                    "parameters": params,
                })

                # Mark this intensity change as handled when it is queued.
                last_auto_triggered_change_at = changed_at

            print(
                f"[AUTO-GENERATION] intensity_a stable for "
                f"{INTENSITY_STABILITY_SECONDS:.0f}s. "
                f"Starting job {job_id}; parameters={params}"
            )

            generation_task = asyncio.create_task(
                run_generation_job(job_id, params)
            )

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            print(f"[AUTO-GENERATION] Monitor error: {exc}")


def generate_one_cell(
    client: StabilityAudioClient,
    job_id: str,
    params: dict,
    column: int,
) -> Path:
    """
    Generate a cell from its original source.

    The generated file is published only after generation completes.
    """
    source = AUDIO_DIR / f"cell_{column}.mp3"
    version_dir = GENERATED_DIR / job_id
    version_dir.mkdir(parents=True, exist_ok=True)

    output = version_dir / f"cell_{column}.mp3"

    intensity, valence = interpolate_emotions(params, column)

    prompt = build_emotion_prompt(
        base_prompt=BASE_SOUND_PROMPT,
        intensity=intensity,
        valence=valence,
    )

    client.transition(
        source_path=source,
        prompt=prompt,
        output_path=output,
        duration=GENERATION_DURATION_SECONDS,
        strength=GENERATION_STRENGTH,
    )

    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError(
            f"Generated audio for cell {column} is missing or empty."
        )

    return output


def publish_cell(job_id: str, column: int, audio_path: Path):
    """Publish a completed audio cell to browser clients."""
    global active_audio_version

    with state_lock:
        if job_id not in audio_versions:
            audio_versions[job_id] = {}

        audio_versions[job_id][column] = audio_path
        active_audio_version = job_id

        published_cells[column] = {
            "version": job_id,
            "url": f"/audio/{column}?version={job_id}",
            "updated_at": time.time(),
        }


def generate_environment_sync(job_id: str, params: dict):
    """Generate and publish each of the five cells sequentially."""
    set_generation_state(
        status="running",
        job_id=job_id,
        progress=0,
        total=GRID_SIZE,
        current_column=0,
        message="Generating cell 1 of 5...",
        error=None,
        started_at=time.time(),
        finished_at=None,
        parameters=params,
    )

    try:
        client = StabilityAudioClient()

        for column in range(GRID_SIZE):
            set_generation_state(
                current_column=column,
                message=f"Generating cell {column + 1} of {GRID_SIZE}...",
            )

            audio_path = generate_one_cell(
                client=client,
                job_id=job_id,
                params=params,
                column=column,
            )

            publish_cell(job_id, column, audio_path)

            set_generation_state(
                progress=column + 1,
                current_column=column,
                message=(
                    f"Published cell {column + 1} of {GRID_SIZE}. "
                    "Playback can use this version now."
                ),
            )

        set_generation_state(
            status="completed",
            progress=GRID_SIZE,
            current_column=None,
            message="All five cells have been generated and published.",
            error=None,
            finished_at=time.time(),
        )

    except Exception as exc:
        print(f"[GENERATION] Job {job_id} failed: {exc}")

        set_generation_state(
            status="failed",
            current_column=None,
            message="Generation stopped. Completed cells remain available.",
            error=str(exc),
            finished_at=time.time(),
        )


async def run_generation_job(job_id: str, params: dict):
    await asyncio.to_thread(generate_environment_sync, job_id, params)


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(PAGE)


@app.get("/health")
async def health():
    with state_lock:
        return {
            "ok": True,
            "position_mode": position_mode,
            "position": dict(current_position),
            "beacons": dict(beacon_rssi),
            "ble": dict(ble_status),
            "gpio": dict(gpio_status),
            "emotion_parameters": dict(current_emotion_parameters),
            "active_audio_version": active_audio_version,
            "generation": dict(generation_state),
            "intensity_stability_seconds": INTENSITY_STABILITY_SECONDS,
            "intensity_change_at": intensity_change_at,
        }


@app.get("/api/gpio")
async def get_gpio_status():
    """Return GPIO status, pin assignments, and current emotion settings."""
    with state_lock:
        return {
            "gpio": dict(gpio_status),
            "pins": dict(GPIO_BUTTON_PINS),
            "parameters": dict(current_emotion_parameters),
        }


@app.get("/position")
async def get_position():
    with state_lock:
        return {
            "x": current_position["x"],
            "y": current_position["y"],
            "column": current_column,
            "source": position_source,
            "mode": position_mode,
            "beacons": dict(beacon_rssi),
            "active_audio_version": active_audio_version,
            "cells": {
                str(col): dict(info)
                for col, info in published_cells.items()
            },
        }


@app.post("/position")
async def set_position(position: PositionUpdate):
    global current_column, smoothed_position_x, position_source

    with state_lock:
        current_position["x"] = position.x
        current_position["y"] = position.y
        smoothed_position_x = position.x
        current_column = x_to_column(position.x)
        position_source = "manual"

    return {
        "ok": True,
        "x": position.x,
        "y": position.y,
        "column": current_column,
    }


@app.post("/mode")
async def set_mode(update: ModeUpdate):
    global position_mode, position_source

    mode = update.mode.strip().lower()

    if mode not in ("automatic", "manual"):
        raise HTTPException(
            status_code=400,
            detail="mode must be 'automatic' or 'manual'",
        )

    with state_lock:
        position_mode = mode
        position_source = "ble" if mode == "automatic" else "manual"

    return {"ok": True, "mode": mode}


@app.post("/api/emotions")
async def save_emotions(params: EmotionParameters):
    """
    Save emotion settings without directly starting generation.

    A change to intensity_a starts or resets the automatic stability timer.
    """
    values = params.dict()
    update_emotion_parameters(values)

    with state_lock:
        current = dict(current_emotion_parameters)

    return {
        "ok": True,
        "parameters": current,
        "auto_generation_delay_seconds": INTENSITY_STABILITY_SECONDS,
    }


@app.post("/api/generate")
async def start_generation(params: EmotionParameters):
    """Manually request generation using the supplied emotion settings."""
    global generation_task
    global intensity_change_at
    global last_auto_triggered_change_at

    values = params.dict()

    with state_lock:
        if generation_state["status"] in ("queued", "running"):
            raise HTTPException(
                status_code=409,
                detail="An audio generation job is already queued or running.",
            )

        old_intensity = current_emotion_parameters["intensity_a"]
        current_emotion_parameters.update(values)

        if abs(values["intensity_a"] - old_intensity) > 1e-9:
            intensity_change_at = time.monotonic()

        # The manual request handles the current settings. This prevents the
        # monitor from automatically generating the same change again.
        if intensity_change_at is not None:
            last_auto_triggered_change_at = intensity_change_at

        job_id = uuid.uuid4().hex[:12]
        audio_versions[job_id] = {}

        generation_state.update({
            "status": "queued",
            "job_id": job_id,
            "progress": 0,
            "total": GRID_SIZE,
            "current_column": None,
            "message": "Generation queued manually.",
            "error": None,
            "started_at": None,
            "finished_at": None,
            "parameters": values,
        })

    generation_task = asyncio.create_task(
        run_generation_job(job_id, values)
    )

    return {
        "ok": True,
        "status": "queued",
        "job_id": job_id,
        "parameters": values,
    }


@app.get("/api/generation/{job_id}")
async def get_generation(job_id: str):
    with state_lock:
        if generation_state["job_id"] != job_id:
            raise HTTPException(
                status_code=404,
                detail="Generation job not found.",
            )

        return dict(generation_state)


@app.get("/api/status")
async def get_live_status():
    """Return live positioning, GPIO, emotion, audio, and generation state."""
    with state_lock:
        return {
            "position": dict(current_position),
            "column": current_column,
            "mode": position_mode,
            "beacons": dict(beacon_rssi),
            "ble": dict(ble_status),
            "gpio": dict(gpio_status),
            "emotion_parameters": dict(current_emotion_parameters),
            "active_audio_version": active_audio_version,
            "cells": {
                str(col): dict(info)
                for col, info in published_cells.items()
            },
            "generation": dict(generation_state),
            "intensity_stability_seconds": INTENSITY_STABILITY_SECONDS,
        }


def audio_file_for_column(
    column: int,
    version: Optional[str],
) -> Path:
    if column < 0 or column >= GRID_SIZE:
        raise HTTPException(status_code=404, detail="Unknown audio column.")

    with state_lock:
        chosen_version = version or published_cells[column]["version"]
        version_map = audio_versions.get(chosen_version)

        if version_map is None or column not in version_map:
            chosen_version = published_cells[column]["version"]
            version_map = audio_versions.get(chosen_version)

        if version_map is None or column not in version_map:
            raise HTTPException(
                status_code=404,
                detail="No audio is available for this column.",
            )

        path = version_map[column]

    if not path.is_file():
        raise HTTPException(status_code=404, detail="Audio file not found.")

    return path


@app.get("/audio/{column}")
async def stream_cell_audio(
    column: int,
    version: Optional[str] = None,
):
    path = audio_file_for_column(column, version)

    return FileResponse(
        path,
        media_type="audio/mpeg",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Pragma": "no-cache",
        },
    )


@app.get("/audio/drone")
async def stream_drone():
    path = AUDIO_DIR / "drone.mp3"

    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Drone audio not found: {path}",
        )

    return FileResponse(
        path,
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-cache"},
    )


# ---------------------------------------------------------------------------
# Browser UI
# ---------------------------------------------------------------------------

PAGE = r"""
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Gallery Audio</title>
<style>
    :root { color-scheme: dark; }
    body {
        font-family: system-ui, sans-serif;
        max-width: 1000px;
        margin: 0 auto;
        padding: 22px;
        background: #151515;
        color: #f1f1f1;
    }
    h1, h2 { font-weight: 550; }
    section {
        margin: 18px 0;
        padding: 18px;
        border: 1px solid #383838;
        border-radius: 12px;
        background: #1d1d1d;
    }
    .row {
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        align-items: center;
    }
    button {
        border: 0;
        border-radius: 7px;
        padding: 10px 14px;
        color: #fff;
        background: #454545;
        cursor: pointer;
    }
    button.primary { background: #476b99; }
    button:disabled { opacity: .5; cursor: wait; }
    .grid {
        display: grid;
        grid-template-columns: repeat(5, 1fr);
        gap: 6px;
        margin-top: 12px;
    }
    .cell {
        padding: 14px 4px;
        text-align: center;
        border: 1px solid #444;
        border-radius: 7px;
        background: #292929;
    }
    .cell.active { background: #476b99; }
    .cell.updated { border-color: #75bd91; }
    label { display: block; margin: 10px 0 5px; }
    input[type="range"] { width: 100%; }
    .control { flex: 1 1 220px; }
    .muted { color: #aaa; font-size: .92rem; }
    .status { white-space: pre-wrap; overflow-wrap: anywhere; }
    .value { font-variant-numeric: tabular-nums; }
</style>
</head>
<body>
<h1>Gallery Audio</h1>
<p class="muted">
    Move between the two beacons to shape the soundscape. A change to
    intensity that remains stable for five seconds automatically generates
    a new soundscape. Generation runs in the background.
</p>

<section>
    <h2>Playback</h2>
    <div class="row">
        <button id="start" class="primary">Start audio</button>
        <button id="stop">Stop audio</button>
        <button id="auto">Automatic positioning</button>
        <button id="manual">Manual positioning</button>
    </div>
    <div class="control">
        <label for="manualX">Manual position: <span id="manualValue">0.0</span></label>
        <input id="manualX" type="range" min="0" max="5" step="0.05" value="0">
    </div>
    <div class="control">
        <label for="crossfade">Crossfade duration:
            <span id="crossfadeValue">4.0 s</span>
        </label>
        <input id="crossfade" type="range" min="0.5" max="12" step="0.5" value="4">
    </div>
    <div class="row">
        <div class="control">
            <label for="cellVolume">Cell volume</label>
            <input id="cellVolume" type="range" min="0" max="1" step="0.01" value="0.8">
        </div>
        <div class="control">
            <label for="droneVolume">Drone volume</label>
            <input id="droneVolume" type="range" min="0" max="1" step="0.01" value="0.25">
        </div>
    </div>
    <p id="playbackStatus" class="status muted">Audio stopped.</p>
    <div id="grid" class="grid"></div>
</section>

<section>
    <h2>Emotion settings</h2>
    <p class="muted">
        Beacon A is the left end of the space; Beacon B is the right end.
        Intensity changes energy and movement. Valence changes the emotional
        character from darker to brighter. Changing intensity starts a
        five-second timer; if it remains stable, generation starts automatically.
    </p>
    <div class="row">
        <div class="control">
            <h3>Beacon A · left</h3>
            <label for="intensityA">Intensity:
                <span id="intensityAValue" class="value">0.50</span>
            </label>
            <input id="intensityA" type="range" min="0" max="1" step="0.05" value="0.5">
            <label for="valenceA">Valence:
                <span id="valenceAValue" class="value">0.00</span>
            </label>
            <input id="valenceA" type="range" min="-1" max="1" step="0.05" value="0">
        </div>
        <div class="control">
            <h3>Beacon B · right</h3>
            <label for="intensityB">Intensity:
                <span id="intensityBValue" class="value">0.50</span>
            </label>
            <input id="intensityB" type="range" min="0" max="1" step="0.05" value="0.5">
            <label for="valenceB">Valence:
                <span id="valenceBValue" class="value">0.00</span>
            </label>
            <input id="valenceB" type="range" min="-1" max="1" step="0.05" value="0">
        </div>
    </div>
    <div class="row">
        <button id="saveEmotions">Save settings only</button>
        <button id="generate" class="primary">Generate next soundscape now</button>
    </div>
    <p id="generationStatus" class="status muted">
        No generation requested yet.
    </p>
</section>

<section>
    <h2>Position and system status</h2>
    <p id="systemStatus" class="status muted">Connecting to server...</p>
</section>

<script>
const GRID_SIZE = 5;

let audioContext = null;
let audioStarted = false;
let automaticMode = true;
let positionX = 0;
let currentColumn = 0;
let sessionId = 0;

let currentCellPlayer = null;
let dronePlayer = null;
let currentCellGain = null;
let droneGain = null;

let activeVersions = Array(GRID_SIZE).fill("original");
let generationPollTimer = null;
let statusPollTimer = null;
let lastGenerationJob = null;
let transitionInProgress = false;
let emotionSaveTimer = null;

const $ = (id) => document.getElementById(id);

function setStatus(id, message) {
    $(id).textContent = message;
}

function getEmotionParams() {
    return {
        intensity_a: Number($("intensityA").value),
        valence_a: Number($("valenceA").value),
        intensity_b: Number($("intensityB").value),
        valence_b: Number($("valenceB").value)
    };
}

function refreshEmotionLabels() {
    for (const [id, digits] of [
        ["intensityA", 2], ["valenceA", 2],
        ["intensityB", 2], ["valenceB", 2]
    ]) {
        $(id + "Value").textContent =
            Number($(id).value).toFixed(digits);
    }
}

function drawGrid() {
    const grid = $("grid");
    grid.innerHTML = "";

    for (let i = 0; i < GRID_SIZE; i++) {
        const cell = document.createElement("div");
        cell.id = "cell-" + i;
        cell.className = "cell";
        cell.innerHTML = `Cell ${i}<br><small>${activeVersions[i]}</small>`;
        grid.appendChild(cell);
    }

    highlightCell(currentColumn);
}

function highlightCell(column) {
    currentColumn = Math.max(0, Math.min(GRID_SIZE - 1, column));

    for (let i = 0; i < GRID_SIZE; i++) {
        const el = $("cell-" + i);
        if (!el) continue;

        el.classList.toggle("active", i === currentColumn);
        el.innerHTML = `Cell ${i}<br><small>${activeVersions[i]}</small>`;
    }
}

function getCrossfadeSeconds() {
    return Number($("crossfade").value);
}

function createCellPlayer(column, version) {
    const audio = new Audio(
        `/audio/${column}?version=${encodeURIComponent(version)}&t=${Date.now()}`
    );

    audio.loop = true;
    audio.preload = "auto";
    audio.crossOrigin = "anonymous";

    const source = audioContext.createMediaElementSource(audio);
    const gain = audioContext.createGain();
    gain.gain.value = 0;

    source.connect(gain);
    gain.connect(audioContext.destination);

    return { audio, gain, source, column, version };
}

function fadeGain(gainNode, from, to, seconds) {
    const now = audioContext.currentTime;
    const end = now + Math.max(0.05, seconds);

    gainNode.gain.cancelScheduledValues(now);
    gainNode.gain.setValueAtTime(from, now);
    gainNode.gain.linearRampToValueAtTime(to, end);
}

async function crossfadeToCell(column, force = false) {
    if (!audioStarted || !audioContext) return;
    if (transitionInProgress) return;

    const version = activeVersions[column] || "original";

    if (
        !force &&
        currentCellPlayer &&
        currentCellPlayer.column === column &&
        currentCellPlayer.version === version
    ) {
        return;
    }

    transitionInProgress = true;

    const mySession = sessionId;
    const nextPlayer = createCellPlayer(column, version);
    const oldPlayer = currentCellPlayer;
    const duration = getCrossfadeSeconds();

    try {
        await new Promise((resolve, reject) => {
            const timeout = setTimeout(
                () => reject(new Error("Audio load timed out")),
                15000
            );

            nextPlayer.audio.addEventListener("canplay", () => {
                clearTimeout(timeout);
                resolve();
            }, { once: true });

            nextPlayer.audio.addEventListener("error", () => {
                clearTimeout(timeout);
                reject(new Error(
                    `Could not load cell ${column} version ${version}`
                ));
            }, { once: true });

            nextPlayer.audio.load();
        });

        await nextPlayer.audio.play();

        if (!audioStarted || mySession !== sessionId) {
            nextPlayer.audio.pause();
            nextPlayer.audio.src = "";
            transitionInProgress = false;
            return;
        }

        const cellVolume = Number($("cellVolume").value);

        nextPlayer.gain.gain.setValueAtTime(
            0,
            audioContext.currentTime
        );

        fadeGain(nextPlayer.gain, 0, cellVolume, duration);

        if (oldPlayer) {
            fadeGain(
                oldPlayer.gain,
                oldPlayer.gain.gain.value,
                0,
                duration
            );
        }

        currentCellPlayer = nextPlayer;
        currentCellGain = nextPlayer.gain;
        highlightCell(column);

        setStatus(
            "playbackStatus",
            `Playing cell ${column} · version ${version}`
        );

        if (oldPlayer) {
            setTimeout(() => {
                oldPlayer.audio.pause();
                oldPlayer.audio.removeAttribute("src");
                oldPlayer.audio.load();

                try { oldPlayer.source.disconnect(); } catch (_) {}
                try { oldPlayer.gain.disconnect(); } catch (_) {}
            }, duration * 1000 + 150);
        }

    } catch (error) {
        nextPlayer.audio.pause();
        nextPlayer.audio.removeAttribute("src");
        nextPlayer.audio.load();

        try { nextPlayer.source.disconnect(); } catch (_) {}
        try { nextPlayer.gain.disconnect(); } catch (_) {}

        setStatus("playbackStatus", error.message);

    } finally {
        transitionInProgress = false;
    }
}

async function startDrone() {
    if (!audioContext || dronePlayer) return;

    const audio = new Audio(`/audio/drone?t=${Date.now()}`);
    audio.loop = true;
    audio.preload = "auto";
    audio.crossOrigin = "anonymous";

    const source = audioContext.createMediaElementSource(audio);
    const gain = audioContext.createGain();

    gain.gain.value = Number($("droneVolume").value);

    source.connect(gain);
    gain.connect(audioContext.destination);

    dronePlayer = { audio, source, gain };
    droneGain = gain;

    try {
        await audio.play();
    } catch (error) {
        setStatus(
            "playbackStatus",
            "Drone could not start. Check that audio/drone.mp3 exists."
        );
    }
}

async function startAudio() {
    if (audioStarted) return;

    audioContext = audioContext || new (
        window.AudioContext || window.webkitAudioContext
    )();

    await audioContext.resume();

    await pollStatus();

    sessionId += 1;
    audioStarted = true;

    $("start").disabled = true;
    $("stop").disabled = false;

    await startDrone();

    const column = Math.max(
        0,
        Math.min(GRID_SIZE - 1, Math.round(positionX))
    );

    await crossfadeToCell(column, true);
    startStatusPolling();
}

function stopAudio() {
    audioStarted = false;
    sessionId += 1;
    transitionInProgress = false;

    if (currentCellPlayer) {
        currentCellPlayer.audio.pause();
        currentCellPlayer.audio.removeAttribute("src");
        currentCellPlayer.audio.load();

        try { currentCellPlayer.source.disconnect(); } catch (_) {}
        try { currentCellPlayer.gain.disconnect(); } catch (_) {}

        currentCellPlayer = null;
        currentCellGain = null;
    }

    if (dronePlayer) {
        dronePlayer.audio.pause();
        dronePlayer.audio.removeAttribute("src");
        dronePlayer.audio.load();

        try { dronePlayer.source.disconnect(); } catch (_) {}
        try { dronePlayer.gain.disconnect(); } catch (_) {}

        dronePlayer = null;
        droneGain = null;
    }

    $("start").disabled = false;
    $("stop").disabled = true;

    setStatus("playbackStatus", "Audio stopped.");
}

async function pollPosition() {
    const response = await fetch("/position", { cache: "no-store" });

    if (!response.ok) {
        throw new Error("Position request failed");
    }

    const data = await response.json();
    positionX = Number(data.x) || 0;

    if (automaticMode) {
        $("manualX").value = positionX;
        $("manualValue").textContent = positionX.toFixed(2);
    }

    const column = Math.max(
        0,
        Math.min(GRID_SIZE - 1, Number(data.column) || 0)
    );

    if (audioStarted && column !== currentColumn) {
        await crossfadeToCell(column);
    } else if (!audioStarted) {
        highlightCell(column);
    }

    return data;
}

async function pollStatus() {
    try {
        const response = await fetch("/api/status", {
            cache: "no-store"
        });

        if (!response.ok) {
            throw new Error("Status request failed");
        }

        const data = await response.json();

        for (let i = 0; i < GRID_SIZE; i++) {
            const cell = data.cells[String(i)];

            if (cell && cell.version) {
                activeVersions[i] = cell.version;
            }
        }

        positionX = Number(data.position.x) || 0;

        if (automaticMode) {
            $("manualX").value = positionX;
            $("manualValue").textContent = positionX.toFixed(2);
        }

        const column = Math.max(
            0,
            Math.min(GRID_SIZE - 1, Number(data.column) || 0)
        );

        drawGrid();

        if (audioStarted) {
            const playingCellVersion = currentCellPlayer
                ? currentCellPlayer.version
                : null;

            const playingCellColumn = currentCellPlayer
                ? currentCellPlayer.column
                : null;

            const currentVersion = activeVersions[column] || "original";

            if (
                playingCellColumn === column &&
                playingCellVersion !== currentVersion
            ) {
                await crossfadeToCell(column, true);
            } else if (column !== currentColumn) {
                await crossfadeToCell(column);
            } else if (
                currentCellPlayer &&
                currentCellPlayer.version !== currentVersion
            ) {
                await crossfadeToCell(column, true);
            }
        } else {
            highlightCell(column);
        }

        const beaconA = data.beacons.a == null
            ? "not seen"
            : `${data.beacons.a.toFixed(0)} dBm`;

        const beaconB = data.beacons.b == null
            ? "not seen"
            : `${data.beacons.b.toFixed(0)} dBm`;

        const gpio = data.gpio || {};
        const emotions = data.emotion_parameters || {};

        setStatus(
            "systemStatus",
            `Mode: ${data.mode}\n` +
            `Position x: ${positionX.toFixed(2)}\n` +
            `Column: ${column}\n` +
            `Beacon A: ${beaconA}\n` +
            `Beacon B: ${beaconB}\n` +
            `BLE: ${data.ble.message}\n` +
            `GPIO: ${gpio.message || "Status unavailable"}\n` +
            `Last GPIO button: ${gpio.last_button ?? "None"}\n` +
            `Intensity A: ${Number(emotions.intensity_a ?? 0.5).toFixed(2)}\n` +
            `Valence A: ${Number(emotions.valence_a ?? 0).toFixed(2)}\n` +
            `Intensity B: ${Number(emotions.intensity_b ?? 0.5).toFixed(2)}\n` +
            `Valence B: ${Number(emotions.valence_b ?? 0).toFixed(2)}\n` +
            `Cell versions: ${activeVersions.join(", ")}`
        );

        if (data.generation) {
            updateGenerationStatus(data.generation);
        }

    } catch (error) {
        setStatus(
            "systemStatus",
            `Server connection error: ${error.message}`
        );
    }
}

function startStatusPolling() {
    if (statusPollTimer) {
        clearInterval(statusPollTimer);
    }

    statusPollTimer = setInterval(pollStatus, 1200);
}

async function setMode(mode) {
    const response = await fetch("/mode", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode })
    });

    if (!response.ok) {
        throw new Error(await response.text());
    }

    automaticMode = mode === "automatic";

    await pollStatus();
}

async function setManualPosition(x) {
    positionX = Number(x);

    await fetch("/position", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ x: positionX, y: 0 })
    });

    $("manualValue").textContent = positionX.toFixed(2);

    if (audioStarted) {
        await crossfadeToCell(Math.round(positionX));
    } else {
        highlightCell(Math.round(positionX));
    }
}

async function saveEmotions() {
    const response = await fetch("/api/emotions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(getEmotionParams())
    });

    const result = await response.json();

    if (!response.ok) {
        throw new Error(
            result.detail || "Could not save emotion settings"
        );
    }

    setStatus(
        "generationStatus",
        "Emotion settings saved. If intensity changed, automatic generation "
        + "will start after it remains stable for five seconds."
    );
}

function updateGenerationStatus(state) {
    const progress = `${state.progress || 0}/${state.total || GRID_SIZE}`;

    let message =
        `${state.message || state.status}\nStatus: ${state.status}`;

    if (state.status === "running" || state.status === "queued") {
        message += `\nCells completed: ${progress}`;
    }

    if (state.error) {
        message += `\nError: ${state.error}`;
    }

    setStatus("generationStatus", message);

    $("generate").disabled =
        state.status === "running" || state.status === "queued";
}

async function pollGenerationJob(jobId) {
    try {
        const response = await fetch(
            `/api/generation/${encodeURIComponent(jobId)}`,
            { cache: "no-store" }
        );

        if (!response.ok) {
            throw new Error(await response.text());
        }

        const state = await response.json();

        updateGenerationStatus(state);
        await pollStatus();

        if (
            state.status === "completed" ||
            state.status === "failed"
        ) {
            if (generationPollTimer) {
                clearInterval(generationPollTimer);
            }

            generationPollTimer = null;
            $("generate").disabled = false;
        }

    } catch (error) {
        setStatus(
            "generationStatus",
            `Could not poll generation job: ${error.message}`
        );

        $("generate").disabled = false;

        if (generationPollTimer) {
            clearInterval(generationPollTimer);
        }

        generationPollTimer = null;
    }
}

async function startGeneration() {
    if (generationPollTimer) {
        clearInterval(generationPollTimer);
        generationPollTimer = null;
    }

    $("generate").disabled = true;

    setStatus(
        "generationStatus",
        "Submitting generation request..."
    );

    try {
        const response = await fetch("/api/generate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(getEmotionParams())
        });

        const result = await response.json();

        if (!response.ok) {
            throw new Error(
                result.detail || "Generation request failed"
            );
        }

        lastGenerationJob = result.job_id;

        setStatus(
            "generationStatus",
            `Generation queued: ${result.job_id}\n` +
            "Each cell will become available as soon as its audio is ready."
        );

        await pollGenerationJob(lastGenerationJob);

        generationPollTimer = setInterval(
            () => pollGenerationJob(lastGenerationJob),
            2500
        );

    } catch (error) {
        $("generate").disabled = false;
        setStatus("generationStatus", error.message);
    }
}


// ---------------------------------------------------------------------------
// Emotion slider debounce and UI events
// ---------------------------------------------------------------------------

function scheduleEmotionUpdate() {
    if (emotionSaveTimer !== null) {
        clearTimeout(emotionSaveTimer);
    }

    // Debounce slider movement so we do not send a request for every
    // individual input event while the user is dragging a slider.
    emotionSaveTimer = setTimeout(async () => {
        emotionSaveTimer = null;

        try {
            const response = await fetch("/api/emotions", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(getEmotionParams())
            });

            const result = await response.json();

            if (!response.ok) {
                throw new Error(
                    result.detail || "Could not update emotion settings"
                );
            }

        } catch (error) {
            setStatus(
                "generationStatus",
                `Could not update emotion settings: ${error.message}`
            );
        }
    }, 250);
}

$("start").addEventListener("click", () => {
    startAudio().catch(
        error => setStatus("playbackStatus", error.message)
    );
});

$("stop").addEventListener("click", stopAudio);

$("auto").addEventListener("click", async () => {
    try {
        await setMode("automatic");
        setStatus(
            "playbackStatus",
            "Automatic positioning enabled."
        );
    } catch (error) {
        setStatus("playbackStatus", error.message);
    }
});

$("manual").addEventListener("click", async () => {
    try {
        await setMode("manual");
        setStatus(
            "playbackStatus",
            "Manual positioning enabled."
        );
    } catch (error) {
        setStatus("playbackStatus", error.message);
    }
});

$("manualX").addEventListener("input", event => {
    $("manualValue").textContent =
        Number(event.target.value).toFixed(2);

    if (!automaticMode) {
        setManualPosition(event.target.value).catch(console.error);
    }
});

$("crossfade").addEventListener("input", event => {
    $("crossfadeValue").textContent =
        Number(event.target.value).toFixed(1) + " s";
});

$("cellVolume").addEventListener("input", event => {
    if (currentCellGain && audioContext) {
        currentCellGain.gain.setTargetAtTime(
            Number(event.target.value),
            audioContext.currentTime,
            0.05
        );
    }
});

$("droneVolume").addEventListener("input", event => {
    if (droneGain && audioContext) {
        droneGain.gain.setTargetAtTime(
            Number(event.target.value),
            audioContext.currentTime,
            0.05
        );
    }
});

for (const id of [
    "intensityA",
    "valenceA",
    "intensityB",
    "valenceB"
]) {
    $(id).addEventListener("input", () => {
        refreshEmotionLabels();
        scheduleEmotionUpdate();
    });
}

$("saveEmotions").addEventListener("click", () => {
    saveEmotions().catch(error =>
        setStatus("generationStatus", error.message)
    );
});

$("generate").addEventListener("click", startGeneration);


// ---------------------------------------------------------------------------
// Initialize browser UI
// ---------------------------------------------------------------------------

$("stop").disabled = true;

refreshEmotionLabels();
drawGrid();
pollStatus();
startStatusPolling();

</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Startup / shutdown
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup():
    global ble_task, intensity_watch_task

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)

    missing = [
        str(AUDIO_DIR / f"cell_{col}.mp3")
        for col in range(GRID_SIZE)
        if not (AUDIO_DIR / f"cell_{col}.mp3").is_file()
    ]

    if missing:
        print("Warning: original audio files missing:")
        for filename in missing:
            print(f"  - {filename}")

    if not (AUDIO_DIR / "drone.mp3").is_file():
        print(f"Warning: missing {AUDIO_DIR / 'drone.mp3'}")

    initialize_gpio_buttons()

    ble_task = asyncio.create_task(ble_scanner_loop())

    intensity_watch_task = asyncio.create_task(
        watch_intensity_stability()
    )

    print(
        "[AUTO-GENERATION] Monitoring intensity_a; "
        f"generation delay is {INTENSITY_STABILITY_SECONDS:.0f} seconds."
    )


@app.on_event("shutdown")
async def shutdown():
    global ble_task, generation_task, intensity_watch_task

    for task in (ble_task, intensity_watch_task):
        if task:
            task.cancel()

            try:
                await task
            except asyncio.CancelledError:
                pass

    for button in gpio_buttons.values():
        button.close()

    gpio_buttons.clear()

    with state_lock:
        gpio_status["available"] = False
        gpio_status["message"] = "GPIO buttons shut down."

    # Generation runs in a worker thread. Do not delete generated files
    # or files currently being used by browser clients during shutdown.
