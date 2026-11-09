# Generative Gallery — Startup Guide

The Generative Gallery consists of three components: the **Curator’s Gallery**, the **Gallery Server**, and the **Bluetooth Beacons**. Together, they let you create soundscapes, play them in an interactive gallery, and use visitors’ proximity to paintings to influence the audio.

## 1. Curator’s Gallery

The Curator’s Gallery is the soundscape creation platform. It lets you upload artwork, generate and edit music prompts using DeepSeek, generate audio with Stability AI, create loops, save and name tracks, and build transitions and intermediate audio cells for the five-cell listening experience.

### Launch

Double-click `LaunchCuratorGallery.command`, or run the following commands from the repository root:

```bash
.venv/bin/python -m pip install -r curator_platform/requirements.txt
.venv/bin/python -m curator_platform.app --port 7870
```

Open [http://127.0.0.1:7870/](http://127.0.0.1:7870/) in your browser.

Add `DEEPSEEK_API_KEY` and `STABILITY_API_KEY` to the root `.env` file. See `.env.example` for the required configuration.

For the full workflow, storage details, provider requests, and tests, see [`curator_platform/README.md`](curator_platform/README.md).

## 2. Gallery Server

The Gallery Server runs the interactive gallery experience. It streams and crossfades audio as visitors move between paintings, tracks device proximity to Bluetooth beacons, and lets visitors influence the soundscape using on-screen sliders or physical buttons. Sliders control the available sound parameters, while physical buttons control **intensity only**.

You must build a circuit and connect to GPIO pins (We integrate into Raspberry Pi 4):
```text
GPIO_BUTTON_PINS = {
    1: 27,  # Physical pin 11: intensity_a = 1.0
    2: 22,  # Physical pin 13: intensity_a = 0.0
}
```

### Install dependencies

Run from the repository root:

```bash
pip install -r gallery_system/requirements.txt
```

### Add audio files

Place the five MP3 files in the root `audio/` directory, using these exact filenames:

```text
audio/
├── cell_0.mp3
├── cell_1.mp3
├── cell_2.mp3
├── cell_3.mp3
└── cell_4.mp3
```

Each file corresponds to one of the five gallery positions. The server uses these files to play and transition between soundscapes as the visitor moves through the space.

### Launch the server

Run from the repository root, replacing `your_ip` with the IP address of the machine running the server:

```bash
uvicorn gallery_system.server:app --host your_ip --port 8000
```

Open `http://your_ip:8000` on a device connected to the same network.

**Note:** Use `127.0.0.1` to access the server locally. To access it from a device use the host machine’s LAN IP address, we use a Raspberry Pi 4

## 3. Bluetooth Beacon Setup

The Bluetooth Beacons provide the proximity-sensing system for the gallery. ESP32 boards placed near paintings advertise their IDs and measure the signal strength of nearby beacons. The Gallery Server uses the resulting proximity information to determine where a visitor is in the gallery and control the corresponding audio experience.

### Flash the ESP32 boards

1. Copy `beacons/proximity_beacons.cpp` into a new Arduino IDE sketch folder and rename it to match the folder name with a `.ino` extension (for example, `proximity_beacons/proximity_beacons.ino`).
2. Install the ESP32 board package, select **Tools → Board → ESP32 Dev Module**, and choose the correct serial port.
3. Set a unique `BEACON_ID` for each board (for example, `1`, `2`, and `3`), then click **Upload**.
4. Open the Serial Monitor at **115200 baud** to verify that each beacon detects nearby beacons and reports their RSSI values.
5. Repeat for every beacon and place the boards near their corresponding paintings.

### Important notes

- Each ESP32 must have a unique `BEACON_ID`.
- All beacons should run the same firmware, with only the ID changed between boards.
- Keep the beacons powered on while the gallery is running.
- Beacon signal strength varies with distance, walls, and human-body obstruction, so test and calibrate placement in the actual gallery space.

## Running the Full Gallery

1. **Create soundscapes** in the Curator’s Gallery.
2. **Prepare the audio files** and place `cell_0.mp3` through `cell_4.mp3` in `audio/`.
3. **Flash and position the ESP32 beacons** near the paintings.
4. **Start the Gallery Server** and open it on the gallery device.
5. **Test the experience:** move between paintings to check proximity tracking and audio transitions, then test the sliders and physical intensity buttons.

