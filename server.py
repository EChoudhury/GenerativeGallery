"""
Gallery Grid Audio Server: two-beacon BLE positioning + crossfading.

Install:
    pip install fastapi uvicorn bleak

Run:
    uvicorn server:app --host 0.0.0.0 --port 8000

Audio files:
    audio/cell_0.mp3
    audio/cell_1.mp3
    audio/cell_2.mp3
    audio/cell_3.mp3
    audio/cell_4.mp3
    audio/drone.mp3

BLE beacon names:
    BEACON-1
    BEACON-2

The Raspberry Pi must be carried by the listener.
The two beacons should be placed at opposite ends of the gallery.

Position is estimated from the difference between the two RSSI readings.
This is a relative estimate, not accurate physical ranging.
"""

import asyncio
import time
from pathlib import Path
from threading import Lock

from bleak import BleakScanner
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field


# ------------------------------------------------------------
# Configuration
# ------------------------------------------------------------

GRID_SIZE = 5
<<<<<<< HEAD
AUDIO_DIR = Path(__file__).resolve().parent / "audio"
=======
GRID_MAX = 5.0
AUDIO_DIR = Path("audio")
>>>>>>> c0f9336acf7d44cbb385a8a6b9e506f3578dac3f

BEACON_NAMES = {
    1: "BEACON-1",
    2: "BEACON-2",
}

# Approximate RSSI difference, in dB, between the two beacons
# when the Pi is near either end of the gallery.
#
# CALIBRATE THIS VALUE IN YOUR ROOM.
# Increase it if the position changes too much.
# Decrease it if the position barely changes.
RSSI_DIFF_AT_END = 12.0

# Smooth noisy RSSI measurements.
RSSI_EMA_ALPHA = 0.25

# Smooth the calculated position as well.
POSITION_EMA_ALPHA = 0.20

RSSI_STALE_SECONDS = 5.0
POSITION_UPDATE_INTERVAL = 0.15

# Prevent tiny changes from constantly switching columns.
COLUMN_HYSTERESIS = 0.12

app = FastAPI(title="Gallery Grid Audio Server")
state_lock = Lock()

current_position = {"x": 2.5, "y": 0.0}
position_source = "default"
position_mode = "ble"

beacon_rssi = {
    beacon_id: {
        "rssi": None,
        "last_seen": None,
        "samples": 0,
    }
    for beacon_id in BEACON_NAMES
}

ble_status = {
    "running": False,
    "last_error": None,
    "last_update": None,
    "rssi_difference": None,
}

ble_task = None
last_estimated_x = None
current_column = 2


# ------------------------------------------------------------
# Models
# ------------------------------------------------------------

class Position(BaseModel):
    x: float = Field(ge=0.0, le=5.0)
    y: float = Field(ge=0.0, le=5.0)


class Mode(BaseModel):
    mode: str


# ------------------------------------------------------------
# Audio files
# ------------------------------------------------------------

def get_audio_path(col: int) -> Path:
<<<<<<< HEAD
    """Prefer lossless curated cells, falling back to the original MP3 grid."""
    wav = AUDIO_DIR / f"cell_{col}.wav"
    if wav.is_file():
        return wav
=======
>>>>>>> c0f9336acf7d44cbb385a8a6b9e506f3578dac3f
    return AUDIO_DIR / f"cell_{col}.mp3"


def get_drone_path() -> Path:
    return AUDIO_DIR / "drone.mp3"


def column_from_x(x: float) -> int:
    """Map X in [0, 5] to one of five columns."""
    return min(GRID_SIZE - 1, max(0, int(x)))


def get_available_columns() -> list[int]:
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    return [
        col for col in range(GRID_SIZE)
        if get_audio_path(col).is_file()
    ]


# ------------------------------------------------------------
# RSSI handling
# ------------------------------------------------------------

def update_beacon_rssi(beacon_id: int, rssi: int) -> None:
    now = time.monotonic()

    with state_lock:
        record = beacon_rssi.get(beacon_id)
        if record is None:
            return

        previous = record["rssi"]
        last_seen = record["last_seen"]

        if (
            previous is None
            or last_seen is None
            or now - last_seen > RSSI_STALE_SECONDS
        ):
            smoothed = float(rssi)
        else:
            smoothed = (
                RSSI_EMA_ALPHA * float(rssi)
                + (1.0 - RSSI_EMA_ALPHA) * previous
            )

        record["rssi"] = smoothed
        record["last_seen"] = now
        record["samples"] += 1


def get_fresh_rssi() -> dict[int, float]:
    now = time.monotonic()
    result = {}

    with state_lock:
        for beacon_id, record in beacon_rssi.items():
            rssi = record["rssi"]
            last_seen = record["last_seen"]

            if (
                rssi is not None
                and last_seen is not None
                and now - last_seen <= RSSI_STALE_SECONDS
            ):
                result[beacon_id] = rssi

    return result


# ------------------------------------------------------------
# One-dimensional position estimation
# ------------------------------------------------------------

def estimate_x(readings: dict[int, float]) -> float | None:
    """
    Estimate position along a line between two beacons.

    Beacon 1 is at X=0.
    Beacon 2 is at X=5.

    If Beacon 1 is stronger, X moves toward zero.
    If Beacon 2 is stronger, X moves toward five.
    """

    if 1 not in readings or 2 not in readings:
        return None

    rssi_1 = readings[1]
    rssi_2 = readings[2]

    # Positive difference means Beacon 1 is stronger.
    difference = rssi_1 - rssi_2

    # Convert relative RSSI difference to X in [0, 5].
    # Equal signal strength gives the midpoint, X=2.5.
    x = 2.5 - (
        difference * GRID_MAX
        / (2.0 * RSSI_DIFF_AT_END)
    )

    return max(0.0, min(GRID_MAX, x))


def update_position_from_ble() -> None:
    global last_estimated_x, current_column, position_source

    with state_lock:
        if position_mode != "ble":
            return

    readings = get_fresh_rssi()
    x = estimate_x(readings)

    # Both beacons must be detected recently.
    if x is None:
        return

    with state_lock:
        if position_mode != "ble":
            return

        if last_estimated_x is None:
            smoothed_x = x
        else:
            smoothed_x = (
                POSITION_EMA_ALPHA * x
                + (1.0 - POSITION_EMA_ALPHA) * last_estimated_x
            )

        last_estimated_x = smoothed_x

        # Apply a small hysteresis around column boundaries.
        # This reduces rapid switching due to RSSI fluctuations.
        proposed_column = column_from_x(smoothed_x)

        if proposed_column != current_column:
            boundary = (
                min(proposed_column, current_column) + 1
            )

            if proposed_column > current_column:
                should_switch = smoothed_x >= (
                    boundary + COLUMN_HYSTERESIS
                )
            else:
                should_switch = smoothed_x <= (
                    boundary - COLUMN_HYSTERESIS
                )

            if should_switch:
                current_column = proposed_column

        current_position["x"] = smoothed_x
        current_position["y"] = 0.0
        position_source = "ble"

        ble_status["last_update"] = time.time()
        ble_status["rssi_difference"] = round(
            readings[1] - readings[2], 1
        )

        print(
            f"RSSI 1={readings[1]:.1f} dBm, "
            f"RSSI 2={readings[2]:.1f} dBm, "
            f"X={smoothed_x:.2f}, "
            f"column={current_column}"
        )


# ------------------------------------------------------------
# BLE scanner
# ------------------------------------------------------------

async def ble_scanner_loop() -> None:
    def detection_callback(device, advertisement_data):
        name = (
            advertisement_data.local_name
            or device.name
            or ""
        )

        for beacon_id, expected_name in BEACON_NAMES.items():
            if name != expected_name:
                continue

            rssi = getattr(advertisement_data, "rssi", None)

            if rssi is None:
                rssi = getattr(device, "rssi", None)

            if rssi is not None:
                update_beacon_rssi(beacon_id, rssi)

            break

    scanner = BleakScanner(
        detection_callback=detection_callback
    )

    try:
        await scanner.start()

        with state_lock:
            ble_status["running"] = True
            ble_status["last_error"] = None

        print("BLE scanner started.")
        print("Waiting for BEACON-1 and BEACON-2...")

        while True:
            update_position_from_ble()
            await asyncio.sleep(POSITION_UPDATE_INTERVAL)

    except asyncio.CancelledError:
        raise

    except Exception as exc:
        with state_lock:
            ble_status["last_error"] = str(exc)
            ble_status["running"] = False

        print(f"BLE scanner error: {exc}")

    finally:
        try:
            await scanner.stop()
        except Exception:
            pass

        with state_lock:
            ble_status["running"] = False


# ------------------------------------------------------------
# Startup / shutdown
# ------------------------------------------------------------

@app.on_event("startup")
async def startup() -> None:
    global ble_task

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    for col in range(GRID_SIZE):
        path = get_audio_path(col)
        print(
            f"{'Found' if path.is_file() else 'Missing'} audio: {path}"
        )

    drone = get_drone_path()
    print(
        f"{'Found' if drone.is_file() else 'Missing'} drone: {drone}"
    )

    ble_task = asyncio.create_task(ble_scanner_loop())


@app.on_event("shutdown")
async def shutdown() -> None:
    global ble_task

    if ble_task is not None:
        ble_task.cancel()
        try:
            await ble_task
        except asyncio.CancelledError:
            pass


# ------------------------------------------------------------
# API endpoints
# ------------------------------------------------------------

@app.get("/position")
def get_position() -> dict:
    with state_lock:
        position = dict(current_position)
        source = position_source
        col = current_column if source == "ble" else column_from_x(position["x"])

    return {
        "position": position,
        "column": col,
        "audio_url": f"/audio/{col}",
        "source": source,
        "mode": position_mode,
    }


@app.post("/position")
def set_manual_position(position: Position) -> dict:
    global position_source, position_mode, current_column

    with state_lock:
        position_mode = "manual"
        position_source = "manual"
        current_position["x"] = position.x
        current_position["y"] = position.y
        current_column = column_from_x(position.x)

        col = current_column

    return {
        "status": "ok",
        "position": dict(current_position),
        "column": col,
        "audio_url": f"/audio/{col}",
    }


<<<<<<< HEAD
@app.get("/audio/{col:int}")
def stream_audio(col: int) -> FileResponse:
    """Stream the MP3 associated with a column."""
    if col < 0 or col >= GRID_SIZE:
=======
@app.post("/mode")
def set_mode(mode: Mode) -> dict:
    global position_mode, position_source, last_estimated_x

    if mode.mode not in ("ble", "manual"):
        raise HTTPException(
            status_code=400,
            detail="Mode must be 'ble' or 'manual'",
        )

    with state_lock:
        position_mode = mode.mode

        if mode.mode == "ble":
            position_source = "ble"
            last_estimated_x = None
        else:
            position_source = "manual"

    return {"status": "ok", "mode": mode.mode}


@app.get("/audio/drone")
def stream_drone() -> FileResponse:
    path = get_drone_path()

    if not path.is_file():
>>>>>>> c0f9336acf7d44cbb385a8a6b9e506f3578dac3f
        raise HTTPException(
            status_code=404,
            detail="Background drone not found: drone.mp3",
        )

    return FileResponse(
        path,
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/audio/{col}")
def stream_audio(col: int) -> FileResponse:
    if col < 0 or col >= GRID_SIZE:
        raise HTTPException(status_code=404, detail="Invalid column")

    path = get_audio_path(col)

    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Audio file not found: {path.name}",
        )

    return FileResponse(
        path,
<<<<<<< HEAD
        media_type="audio/wav" if path.suffix == ".wav" else "audio/mpeg",
        headers={
            "Cache-Control": "no-cache",
        },
        filename=None,
    )


@app.get("/audio/drone")
def stream_drone() -> FileResponse:
    """Stream the shared background drone."""
    path = get_drone_path()

    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Background drone not found: drone.mp3",
        )

    return FileResponse(
        path,
        media_type="audio/mpeg",
        headers={
            "Cache-Control": "no-cache",
        },
        filename=None,
=======
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-cache"},
>>>>>>> c0f9336acf7d44cbb385a8a6b9e506f3578dac3f
    )


@app.get("/health")
def health() -> dict:
    available = get_available_columns()
    now = time.monotonic()

    with state_lock:
        beacons = {}

        for beacon_id, record in beacon_rssi.items():
            last_seen = record["last_seen"]
            age = (
                None if last_seen is None
                else round(now - last_seen, 2)
            )

            beacons[BEACON_NAMES[beacon_id]] = {
                "rssi": (
                    None if record["rssi"] is None
                    else round(record["rssi"], 1)
                ),
                "age_seconds": age,
                "samples": record["samples"],
                "fresh": (
                    last_seen is not None
                    and now - last_seen <= RSSI_STALE_SECONDS
                ),
            }

        position = dict(current_position)
        source = position_source
        mode = position_mode
        ble = dict(ble_status)
        col = current_column if source == "ble" else column_from_x(position["x"])

    return {
        "status": "ok" if available else "no_audio",
        "loaded_columns": available,
        "missing_files": [
            str(get_audio_path(c))
            for c in range(GRID_SIZE)
            if c not in available
        ],
        "drone_available": get_drone_path().is_file(),
        "position": position,
        "position_source": source,
        "position_mode": mode,
        "current_column": col,
        "ble": {
            **ble,
            "beacons": beacons,
        },
    }


# ------------------------------------------------------------
# Browser UI
# ------------------------------------------------------------

@app.get("/")
def home() -> HTMLResponse:
        return HTMLResponse(r"""
    <!doctype html>
    <html lang="en">
    <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Gallery Audio Grid</title>
    <style>
    body {
        font-family: sans-serif;
        max-width: 760px;
        margin: 40px auto;
        padding: 0 20px;
    }
    .control { margin: 22px 0; }
    input[type=range] { width: 100%; }
    button { padding: 10px 16px; margin: 4px; cursor: pointer; }
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
    #status { margin-top: 20px; line-height: 1.5; overflow-wrap: anywhere; }
    .note { color: #555; font-size: .9rem; }
    .value { font-weight: bold; }
    </style>
    </head>
    <body>
    <h1>Gallery Audio Grid</h1>

    <p>
    The Raspberry Pi estimates your position between two BLE beacons.
    Moving between columns changes the soundscape; the drone continues
    in the background.
    </p>

    <button id="start">Start audio</button>
    <button id="stop" disabled>Stop audio</button>
    <button id="bleMode">Use BLE position</button>
    <button id="manualMode">Manual test mode</button>

    <div class="control">
    <label for="crossfade">
    Crossfade duration: <span id="crossfadeValue">3.00</span> seconds
    </label>
    <input id="crossfade" type="range" min=".25" max="10" step=".25" value="3">
    </div>

    <div class="control">
    <label for="droneVolume">
    Drone volume: <span id="droneValue">15</span>%
    </label>
    <input id="droneVolume" type="range" min="0" max="50" value="15">
    </div>

    <div class="control">
    <label for="trackVolume">
    Soundscape volume: <span id="trackValue">100</span>%
    </label>
    <input id="trackVolume" type="range" min="0" max="100" value="100">
    </div>

    <div id="manualControls" hidden>
    <div class="control">
    <label for="x">Position X: <span id="xvalue">2.50</span></label>
    <input id="x" type="range" min="0" max="5" step=".05" value="2.5">
    </div>
    <button id="sendManual">Send manual position</button>
    </div>

    <div id="status">Waiting for BLE readings.</div>
    <div id="grid"></div>

    <script>
    const SIZE = 5;
    const $ = id => document.getElementById(id);

    let audioContext = null;
    let players = [];
    let dronePlayer = null;
    let trackMasterGain = null;
    let droneMasterGain = null;

    let activeIndex = 0;
    let currentColumn = null;
    let audioStarted = false;
    let automaticMode = true;
    let transitionId = 0;
    let cleanupTimer = null;
    let pollTimer = null;
    let lastPosition = null;

    for (let row = 0; row < SIZE; row++) {
        for (let col = 0; col < SIZE; col++) {
            const cell = document.createElement("div");
            cell.className = "cell";
            cell.id = `cell-${col}-${row}`;
            cell.textContent = `Column ${col}`;
            $("grid").appendChild(cell);
        }
    }

    function updateGrid(col) {
        document.querySelectorAll(".cell").forEach(cell => {
            cell.classList.toggle("active", cell.id.startsWith(`cell-${col}-`));
        });
    }

    function createPlayer(destination) {
        const audio = new Audio();
        audio.preload = "none";
        audio.loop = true;
        audio.crossOrigin = "anonymous";

        const source = audioContext.createMediaElementSource(audio);
        const gain = audioContext.createGain();
        source.connect(gain);
        gain.connect(destination);
        gain.gain.value = 0;

        return { audio, gain, targetColumn: null };
    }

    function initializeAudio() {
        if (audioContext) return;

        audioContext = new AudioContext();

        trackMasterGain = audioContext.createGain();
        trackMasterGain.gain.value = Number($("trackVolume").value) / 100;
        trackMasterGain.connect(audioContext.destination);

        players = [
            createPlayer(trackMasterGain),
            createPlayer(trackMasterGain)
        ];

        droneMasterGain = audioContext.createGain();
        droneMasterGain.gain.value = Number($("droneVolume").value) / 100;
        droneMasterGain.connect(audioContext.destination);

        dronePlayer = createPlayer(droneMasterGain);
    }

    function resetPlayer(player) {
        player.audio.pause();
        player.audio.removeAttribute("src");
        player.audio.load();
        player.targetColumn = null;

        const now = audioContext.currentTime;
        player.gain.gain.cancelScheduledValues(now);
        player.gain.gain.setValueAtTime(0, now);
    }

    async function switchAudio(col, immediate = false) {
        if (!audioStarted) return;

        if (currentColumn === col &&
            players.some(p => p.targetColumn === col && !p.audio.paused)) {
            return;
        }

        const id = ++transitionId;
        if (cleanupTimer !== null) clearTimeout(cleanupTimer);

        let outgoingIndex = activeIndex;
        let incomingIndex = 1 - activeIndex;

        if (players[1 - activeIndex].gain.gain.value >
            players[activeIndex].gain.gain.value) {
            outgoingIndex = 1 - activeIndex;
            incomingIndex = activeIndex;
        }

        const outgoing = players[outgoingIndex];
        const incoming = players[incomingIndex];

        const now = audioContext.currentTime;
        for (const player of players) {
            player.gain.gain.cancelScheduledValues(now);
            player.gain.gain.setValueAtTime(player.gain.gain.value, now);
        }

        resetPlayer(incoming);
        incoming.targetColumn = col;
        incoming.audio.src = `/audio/${col}`;
        incoming.audio.load();

        const duration = immediate ? 0 : Number($("crossfade").value);
        $("status").textContent = `Loading column ${col}...`;

        try {
            await incoming.audio.play();

            if (id !== transitionId || !audioStarted) {
                resetPlayer(incoming);
                return;
            }

            const start = audioContext.currentTime;
            incoming.gain.gain.cancelScheduledValues(start);
            incoming.gain.gain.setValueAtTime(0, start);

            outgoing.gain.gain.cancelScheduledValues(start);
            outgoing.gain.gain.setValueAtTime(
                outgoing.gain.gain.value, start
            );

            if (duration <= .01) {
                incoming.gain.gain.setValueAtTime(1, start);
                outgoing.gain.gain.setValueAtTime(0, start);
            } else {
                incoming.gain.gain.linearRampToValueAtTime(1, start + duration);
                outgoing.gain.gain.linearRampToValueAtTime(0, start + duration);
            }

            activeIndex = incomingIndex;
            currentColumn = col;
            updateGrid(col);

            cleanupTimer = setTimeout(() => {
                if (id === transitionId) resetPlayer(outgoing);
            }, duration * 1000 + 150);

            $("status").textContent =
                `Playing column ${col}; crossfade ${duration.toFixed(2)} s.`;
        } catch (error) {
            if (id === transitionId) {
                $("status").textContent =
                    `Could not play column ${col}: ${error.message}`;
            }
        }
    }

    async function startDrone() {
        dronePlayer.audio.src = "/audio/drone";
        dronePlayer.audio.load();

        try {
            await dronePlayer.audio.play();
            const now = audioContext.currentTime;
            dronePlayer.gain.gain.cancelScheduledValues(now);
            dronePlayer.gain.gain.setValueAtTime(0, now);
            dronePlayer.gain.gain.linearRampToValueAtTime(1, now + 1.5);
        } catch (error) {
            $("status").textContent = "Drone unavailable: " + error.message;
        }
    }

    async function pollPosition() {
        try {
            const response = await fetch("/position", { cache: "no-store" });
            if (!response.ok) throw new Error("Position request failed");

            const data = await response.json();
            const x = Number(data.position.x);
            const col = Number(data.column);
            lastPosition = { x, col };

            if (!automaticMode) return;

            $("x").value = x;
            $("xvalue").textContent = x.toFixed(2);
            updateGrid(col);

            if (audioStarted && col !== currentColumn) {
                await switchAudio(col);
            } else if (!audioStarted) {
                currentColumn = col;
            }

            $("status").textContent =
                `BLE mode | X=${x.toFixed(2)} | Column=${col} | Source=${data.source}`;
        } catch (error) {
            $("status").textContent = "Position error: " + error.message;
        }
    }

    function startPolling() {
        if (pollTimer !== null) clearInterval(pollTimer);
        pollPosition();
        pollTimer = setInterval(pollPosition, 500);
    }

    $("start").addEventListener("click", async () => {
        initializeAudio();

        try {
            await audioContext.resume();
            audioStarted = true;
            $("start").disabled = true;
            $("stop").disabled = false;

            startDrone();

            if (automaticMode) {
                await pollPosition();
                const col = lastPosition ? lastPosition.col : 2;
                currentColumn = null;
                await switchAudio(col, true);
            } else {
                const col = Math.min(4, Math.floor(Number($("x").value)));
                currentColumn = null;
                await switchAudio(col, true);
            }

            startPolling();
        } catch (error) {
            $("status").textContent = "Could not start audio: " + error.message;
            audioStarted = false;
            $("start").disabled = false;
            $("stop").disabled = true;
        }
    });

    $("stop").addEventListener("click", () => {
        transitionId++;
        if (cleanupTimer !== null) clearTimeout(cleanupTimer);

        audioStarted = false;
        players.forEach(resetPlayer);
        if (dronePlayer) resetPlayer(dronePlayer);

        currentColumn = null;
        $("start").disabled = false;
        $("stop").disabled = true;
        $("status").textContent = "Audio stopped.";
    });

    $("bleMode").addEventListener("click", async () => {
        await fetch("/mode", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ mode: "ble" })
        });

        automaticMode = true;
        $("manualControls").hidden = true;
        $("status").textContent = "BLE mode enabled.";
        pollPosition();
    });

    $("manualMode").addEventListener("click", async () => {
        await fetch("/mode", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ mode: "manual" })
        });

        automaticMode = false;
        $("manualControls").hidden = false;
        $("status").textContent = "Manual test mode enabled.";
    });

    $("sendManual").addEventListener("click", async () => {
        const x = Number($("x").value);
        $("xvalue").textContent = x.toFixed(2);

        try {
            const response = await fetch("/position", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ x, y: 0 })
            });

            if (!response.ok) throw new Error("Manual position update failed");

            const data = await response.json();
            const col = data.column;
            updateGrid(col);

            if (audioStarted && col !== currentColumn) {
                await switchAudio(col);
            } else {
                currentColumn = col;
            }

            $("status").textContent =
                `Manual X=${x.toFixed(2)} | Column=${col}`;
        } catch (error) {
            $("status").textContent = error.message;
        }
    });

    $("crossfade").addEventListener("input", () => {
        $("crossfadeValue").textContent =
            Number($("crossfade").value).toFixed(2);
    });

    $("droneVolume").addEventListener("input", () => {
        $("droneValue").textContent = $("droneVolume").value;

        if (droneMasterGain && audioContext) {
            droneMasterGain.gain.setTargetAtTime(
                Number($("droneVolume").value) / 100,
                audioContext.currentTime,
                .05
            );
        }
    });

    $("trackVolume").addEventListener("input", () => {
        $("trackValue").textContent = $("trackVolume").value;

        if (trackMasterGain && audioContext) {
            trackMasterGain.gain.setTargetAtTime(
                Number($("trackVolume").value) / 100,
                audioContext.currentTime,
                .05
            );
        }
    });

    $("x").addEventListener("input", () => {
        $("xvalue").textContent = Number($("x").value).toFixed(2);
    });

    startPolling();
    </script>
    </body>
    </html>
    """)

