"""
Gallery Grid Audio Server

Install:
    pip install fastapi uvicorn

Run:
    uvicorn server:app --host 192.168.125.250 --port 8000

Audio files:
    audio/cell_0.mp3
    audio/cell_1.mp3
    audio/cell_2.mp3
    audio/cell_3.mp3
    audio/cell_4.mp3
    audio/drone.mp3

API:
    POST /position
        {"x": 2.1, "y": 3.4}

    GET /audio/{col}
        Streams the MP3 associated with a column.

    GET /audio/drone
        Streams the continuous background drone.

    GET /health
        Reports available and missing audio files.

Coordinates are in the range [0, 5].
The five columns are centered at x = 0.5, 1.5, 2.5, 3.5, 4.5.
The Y coordinate is ignored when selecting audio.

Crossfading and drone mixing happen in the browser using the Web Audio API.
"""

from pathlib import Path
from threading import Lock

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------

GRID_SIZE = 5
AUDIO_DIR = Path("audio")

app = FastAPI(title="Gallery Grid Audio Server")


# ---------------------------------------------------------------------
# State
# ---------------------------------------------------------------------

class Position(BaseModel):
    x: float = Field(ge=0.0, le=5.0)
    y: float = Field(ge=0.0, le=5.0)


position_lock = Lock()
current_position = {"x": 2.5, "y": 2.5}


# ---------------------------------------------------------------------
# Audio file availability
# ---------------------------------------------------------------------

def get_audio_path(col: int) -> Path:
    """Return the MP3 file for a column."""
    return AUDIO_DIR / f"cell_{col}.mp3"


def get_drone_path() -> Path:
    """Return the shared drone MP3."""
    return AUDIO_DIR / "drone.mp3"


def get_available_columns() -> list[int]:
    """Return the columns whose MP3 files exist."""
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    return [
        col
        for col in range(GRID_SIZE)
        if get_audio_path(col).is_file()
    ]


@app.on_event("startup")
def startup() -> None:
    """Report available and missing audio files."""
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    for col in range(GRID_SIZE):
        path = get_audio_path(col)

        if path.is_file():
            print(f"Found audio: {path}")
        else:
            print(f"Missing audio file: {path}")

    drone_path = get_drone_path()

    if drone_path.is_file():
        print(f"Found background drone: {drone_path}")
    else:
        print(
            f"Missing background drone: {drone_path}. "
            "The gallery will still work without it."
        )


# ---------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------

@app.post("/position")
def update_position(position: Position) -> dict:
    """Update the listener's position in the room."""
    with position_lock:
        current_position["x"] = position.x
        current_position["y"] = position.y

    col = min(GRID_SIZE - 1, int(position.x))

    return {
        "status": "ok",
        "position": {
            "x": position.x,
            "y": position.y,
        },
        "column": col,
        "audio_url": f"/audio/{col}",
    }


@app.get("/audio/{col}")
def stream_audio(col: int) -> FileResponse:
    """Stream the MP3 associated with a column."""
    if col < 0 or col >= GRID_SIZE:
        raise HTTPException(
            status_code=404,
            detail="Invalid column",
        )

    path = get_audio_path(col)

    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Audio file not found: {path.name}",
        )

    return FileResponse(
        path,
        media_type="audio/mpeg",
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
    )


@app.get("/health")
def health() -> dict:
    """Report available column tracks and drone."""
    available = get_available_columns()

    missing = [
        str(get_audio_path(col))
        for col in range(GRID_SIZE)
        if col not in available
    ]

    drone_available = get_drone_path().is_file()

    with position_lock:
        position = dict(current_position)

    return {
        "status": "ok" if available else "no_audio",
        "loaded_columns": available,
        "loaded_count": len(available),
        "missing_files": missing,
        "drone_available": drone_available,
        "drone_file": str(get_drone_path()),
        "position": position,
        "current_column": min(
            GRID_SIZE - 1,
            int(position["x"]),
        ),
    }


# ---------------------------------------------------------------------
# Browser test page
# ---------------------------------------------------------------------

@app.get("/")
def home() -> HTMLResponse:
    """Serve the interactive gallery test page."""
    return HTMLResponse(
        """
<!doctype html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">

    <title>Gallery Audio Grid</title>

    <style>
        body {
            font-family: sans-serif;
            max-width: 700px;
            margin: 40px auto;
            padding: 0 20px;
        }

        .control {
            margin: 24px 0;
        }

        input[type="range"] {
            width: 100%;
        }

        button {
            padding: 10px 16px;
            cursor: pointer;
        }

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

        .active {
            background: #a7d8ff;
        }

        #status {
            margin-top: 20px;
            line-height: 1.5;
        }

        .value {
            font-weight: bold;
        }

        .note {
            color: #555;
            font-size: 0.9rem;
        }
    </style>
</head>

<body>
    <h1>Gallery Audio Grid</h1>

    <p>
        Move horizontally across the grid to switch soundscapes.
        The background drone continues while the column tracks
        crossfade. The Y coordinate does not affect the audio.
    </p>

    <button id="start">Start audio</button>
    <button id="stop" disabled>Stop audio</button>

    <div class="control">
        <label for="x">
            X position:
            <span class="value" id="xvalue">2.50</span>
        </label>

        <input
            id="x"
            type="range"
            min="0"
            max="5"
            step="0.05"
            value="2.5"
        >
    </div>

    <div class="control">
        <label for="y">
            Y position:
            <span class="value" id="yvalue">2.50</span>
        </label>

        <input
            id="y"
            type="range"
            min="0"
            max="5"
            step="0.05"
            value="2.5"
        >
    </div>

    <div class="control">
        <label for="crossfade">
            Crossfade duration:
            <span class="value" id="crossfadeValue">3.0</span>
            seconds
        </label>

        <input
            id="crossfade"
            type="range"
            min="0.25"
            max="10"
            step="0.25"
            value="3"
        >

        <p class="note">
            Shorter transitions feel more immediate. Longer
            transitions create a more gradual change.
        </p>
    </div>

    <div class="control">
        <label for="droneVolume">
            Drone volume:
            <span class="value" id="droneValue">15</span>%
        </label>

        <input
            id="droneVolume"
            type="range"
            min="0"
            max="50"
            step="1"
            value="15"
        >
    </div>

    <div class="control">
        <label for="trackVolume">
            Soundscape volume:
            <span class="value" id="trackValue">100</span>%
        </label>

        <input
            id="trackVolume"
            type="range"
            min="0"
            max="100"
            step="1"
            value="100"
        >
    </div>

    <div id="status">Audio stopped.</div>

    <div id="grid"></div>

    <script>
        const xSlider = document.getElementById("x");
        const ySlider = document.getElementById("y");
        const crossfadeSlider = document.getElementById("crossfade");
        const droneSlider = document.getElementById("droneVolume");
        const trackSlider = document.getElementById("trackVolume");

        const status = document.getElementById("status");
        const startButton = document.getElementById("start");
        const stopButton = document.getElementById("stop");

        let audioContext = null;
        let players = [];
        let dronePlayer = null;

        let activeIndex = 0;
        let currentColumn = null;
        let audioStarted = false;

        // Incremented on each transition to invalidate stale loads.
        let transitionId = 0;

        // Currently scheduled transition cleanup.
        let transitionCleanup = null;

        // -----------------------------------------------------------------
        // Grid
        // -----------------------------------------------------------------

        for (let row = 4; row >= 0; row--) {
            for (let col = 0; col < 5; col++) {
                const cell = document.createElement("div");

                cell.className = "cell";
                cell.id = `cell-${col}-${row}`;
                cell.textContent = `${col}, ${row}`;

                document.getElementById("grid").appendChild(cell);
            }
        }

        function columnFromX(x) {
            return Math.min(4, Math.floor(x));
        }

        function updateGrid(col) {
            document.querySelectorAll(".cell").forEach(cell => {
                cell.classList.remove("active");
            });

            for (let row = 0; row < 5; row++) {
                document
                    .getElementById(`cell-${col}-${row}`)
                    .classList.add("active");
            }
        }

        // -----------------------------------------------------------------
        // Web Audio setup
        // -----------------------------------------------------------------

        function createPlayer() {
            const audio = new Audio();
            audio.preload = "none";
            audio.loop = true;
            audio.crossOrigin = "anonymous";

            const source = audioContext.createMediaElementSource(audio);
            const gain = audioContext.createGain();

            source.connect(gain);
            gain.connect(audioContext.destination);

            return {
                audio,
                gain,
                source,
                targetColumn: null
            };
        }

        function initializeAudio() {
            if (audioContext) return;

            audioContext = new AudioContext();

            players = [
                createPlayer(),
                createPlayer()
            ];

            dronePlayer = createPlayer();

            players.forEach(player => {
                player.gain.gain.value = 0;
            });

            dronePlayer.gain.gain.value =
                Number(droneSlider.value) / 100;
        }

        // -----------------------------------------------------------------
        // Transition handling
        // -----------------------------------------------------------------

        function cancelTransitionCleanup() {
            if (transitionCleanup !== null) {
                clearTimeout(transitionCleanup);
                transitionCleanup = null;
            }
        }

        function rampGain(gainNode, target, now, duration) {
            const param = gainNode.gain;

            // Continue smoothly from the current scheduled value.
            const currentValue = param.value;

            param.cancelScheduledValues(now);
            param.setValueAtTime(currentValue, now);

            if (duration <= 0.01) {
                param.setValueAtTime(target, now);
            } else {
                param.linearRampToValueAtTime(
                    target,
                    now + duration
                );
            }
        }

        async function switchAudio(col, immediate = false) {
            if (!audioStarted) return;

            if (
                col === currentColumn &&
                players[activeIndex].targetColumn === col
            ) {
                return;
            }

            const id = ++transitionId;

            cancelTransitionCleanup();

            const oldPlayer = players[activeIndex];
            const nextIndex = 1 - activeIndex;
            const nextPlayer = players[nextIndex];

            currentColumn = col;
            nextPlayer.targetColumn = col;

            const duration = immediate
                ? 0
                : Number(crossfadeSlider.value);

            status.textContent =
                `Loading soundscape for column ${col}...`;

            // Prepare the inactive player at zero gain.
            nextPlayer.gain.gain.cancelScheduledValues(
                audioContext.currentTime
            );
            nextPlayer.gain.gain.setValueAtTime(
                0,
                audioContext.currentTime
            );

            nextPlayer.audio.pause();
            nextPlayer.audio.src = `/audio/${col}`;
            nextPlayer.audio.load();

            try {
                await nextPlayer.audio.play();

                // A newer transition may have started during loading.
                if (id !== transitionId) {
                    nextPlayer.audio.pause();
                    return;
                }

                const now = audioContext.currentTime;

                const oldTarget = oldPlayer.targetColumn;

                rampGain(
                    nextPlayer.gain,
                    Number(trackSlider.value) / 100,
                    now,
                    duration
                );

                if (oldTarget !== null && !oldPlayer.audio.paused) {
                    rampGain(
                        oldPlayer.gain,
                        0,
                        now,
                        duration
                    );
                }

                activeIndex = nextIndex;

                transitionCleanup = setTimeout(() => {
                    if (id !== transitionId) return;

                    if (oldTarget !== null) {
                        oldPlayer.audio.pause();
                        oldPlayer.audio.removeAttribute("src");
                        oldPlayer.audio.load();
                        oldPlayer.targetColumn = null;
                    }

                    transitionCleanup = null;
                }, duration * 1000 + 150);

                status.textContent =
                    `Playing column ${col}. ` +
                    `Crossfade: ${duration.toFixed(2)} seconds.`;

            } catch (error) {
                if (id !== transitionId) return;

                status.textContent =
                    `Could not play column ${col}: ${error.message}`;
            }
        }

        // -----------------------------------------------------------------
        // Drone
        // -----------------------------------------------------------------

        async function startDrone() {
            dronePlayer.audio.src = "/audio/drone";
            dronePlayer.audio.load();

            try {
                await dronePlayer.audio.play();

                const now = audioContext.currentTime;

                dronePlayer.gain.gain.cancelScheduledValues(now);
                dronePlayer.gain.gain.setValueAtTime(0, now);
                dronePlayer.gain.gain.linearRampToValueAtTime(
                    Number(droneSlider.value) / 100,
                    now + 1.5
                );

                return true;
            } catch (error) {
                console.warn("Background drone unavailable:", error);
                status.textContent =
                    "Drone unavailable; continuing without it.";

                return false;
            }
        }

        // -----------------------------------------------------------------
        // Position updates
        // -----------------------------------------------------------------

        async function sendPosition() {
            const x = Number(xSlider.value);
            const y = Number(ySlider.value);
            const col = columnFromX(x);

            document.getElementById("xvalue").textContent =
                x.toFixed(2);

            document.getElementById("yvalue").textContent =
                y.toFixed(2);

            updateGrid(col);

            try {
                const response = await fetch("/position", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({ x, y })
                });

                if (!response.ok) {
                    throw new Error("Position update failed");
                }
            } catch (error) {
                status.textContent =
                    "Could not update position: " + error.message;
                return;
            }

            // Y does not affect the audio selection.
            if (col === currentColumn) return;

            if (!audioStarted) {
                currentColumn = col;
                status.textContent = `Column ${col}: ready to play`;
                return;
            }

            await switchAudio(col);
        }

        // -----------------------------------------------------------------
        // Controls
        // -----------------------------------------------------------------

        startButton.addEventListener("click", async () => {
            initializeAudio();

            try {
                await audioContext.resume();

                audioStarted = true;
                startButton.disabled = true;
                stopButton.disabled = false;

                const col = columnFromX(Number(xSlider.value));

                // Start the drone independently of the soundscape.
                await startDrone();

                // Start the first track without crossfading from silence.
                currentColumn = null;
                await switchAudio(col, true);

            } catch (error) {
                status.textContent =
                    "Could not start audio: " + error.message;

                startButton.disabled = false;
                stopButton.disabled = true;
            }
        });

        stopButton.addEventListener("click", () => {
            transitionId++;
            cancelTransitionCleanup();

            audioStarted = false;

            players.forEach(player => {
                player.audio.pause();
                player.audio.removeAttribute("src");
                player.audio.load();

                player.gain.gain.cancelScheduledValues(
                    audioContext.currentTime
                );
                player.gain.gain.setValueAtTime(
                    0,
                    audioContext.currentTime
                );

                player.targetColumn = null;
            });

            if (dronePlayer) {
                dronePlayer.audio.pause();
                dronePlayer.audio.removeAttribute("src");
                dronePlayer.audio.load();

                dronePlayer.gain.gain.cancelScheduledValues(
                    audioContext.currentTime
                );
                dronePlayer.gain.gain.setValueAtTime(
                    0,
                    audioContext.currentTime
                );
            }

            currentColumn = null;
            activeIndex = 0;

            startButton.disabled = false;
            stopButton.disabled = true;

            status.textContent = "Audio stopped.";
        });

        crossfadeSlider.addEventListener("input", () => {
            document.getElementById("crossfadeValue").textContent =
                Number(crossfadeSlider.value).toFixed(2);
        });

        droneSlider.addEventListener("input", () => {
            const volume = Number(droneSlider.value) / 100;

            document.getElementById("droneValue").textContent =
                droneSlider.value;

            if (dronePlayer && audioStarted) {
                const now = audioContext.currentTime;

                rampGain(
                    dronePlayer.gain,
                    volume,
                    now,
                    0.1
                );
            }
        });

        trackSlider.addEventListener("input", () => {
            document.getElementById("trackValue").textContent =
                trackSlider.value;

            if (!audioStarted) return;

            const now = audioContext.currentTime;
            const target = Number(trackSlider.value) / 100;

            players.forEach(player => {
                if (
                    player.targetColumn !== null &&
                    !player.audio.paused
                ) {
                    rampGain(player.gain, target, now, 0.1);
                }
            });
        });

        xSlider.addEventListener("input", sendPosition);
        ySlider.addEventListener("input", sendPosition);

        // Initialize position and grid without starting playback.
        sendPosition();
    </script>
</body>
</html>
        """
    )

