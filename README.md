# Living Gallery — audio engine starter

## New: Curator’s Gallery platform

The new local website combines artwork upload, DeepSeek image-to-music-prompt interpretation, editable prompts, Stability music generation, loop creation with naming, a saved music library, two-song transitions, automatic intermediate cells and a five-cell listening grid.

Double-click **`打开策展工作台.command`**, or run:

```bash
.venv/bin/python -m pip install -r curator_platform/requirements.txt
.venv/bin/python -m curator_platform.app --port 7870
```

Open <http://127.0.0.1:7870/>. Add `DEEPSEEK_API_KEY` and `STABILITY_API_KEY` to your root `.env` (see `.env.example`). The earlier grid remains separate. See [the curator platform guide](curator_platform/README.md) for the complete workflow, storage, provider requests, and tests.

---

A small first milestone for the ADE hackathon prototype:
- continuously plays looping WAV layers
- smoothly crossfades between `storm`, `machine`, and `dream`
- lets you switch artworks from the terminal
- includes generated placeholder audio so you can test before using Stable Audio

## 1. Requirements

Use Python 3.10+ if possible. On Windows, run these commands in PowerShell from this folder.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If PowerShell blocks activation, you can use the venv Python directly:
```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

On macOS/Linux, activate with `source .venv/bin/activate`.

## 2. Create placeholder sounds

```powershell
python make_demo_assets.py
```

This creates loopable test WAV files in `assets/`. They are synthesized placeholders, not the final generative audio.

## 3. Run the mixer

```powershell
python gallery_engine.py
```

Type `storm`, `machine`, or `dream` and press Enter to switch. Type `q` to quit.
Use headphones or start with low volume.

If you get an audio-device error, run:
```powershell
python -c "import sounddevice as sd; print(sd.query_devices())"
```
Then share the error and device list. On Windows, make sure the intended output device is enabled in Sound settings.

## 4. Replace placeholders with Stable Audio

Keep the filenames the same, or update `gallery.json` to match your generated WAV filenames. The mixer loads WAV files at startup, so stop and restart it after replacing assets.

Stable Audio 3's official repo and CLI instructions:
https://github.com/Stability-AI/stable-audio-3

Once Stable Audio is installed, generate clips offline rather than inside the real-time audio callback. Example CLI command from the official repo:
```bash
stable-audio --model small-music -p "Atmospheric dark ambient soundscape, slow evolving low drone, no vocals, no percussion" --duration 30 -o assets/storm_drone.wav
```

Generate distinct layers for each artwork, for example:
- storm: low drone + sparse granular/rain texture
- machine: pulsing mechanical ambience + metallic texture
- dream: warm sustained pad + airy shimmer

The mixer currently loops each file. If a generated clip has a noticeable seam, try a different generation or we can add loop-point/crossfade processing next.
