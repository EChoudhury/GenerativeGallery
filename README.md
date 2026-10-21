# Living Gallery — generative music and spatial transitions

A local workbench for generating painting-inspired music with Stability AI, curating loops and connecting passages, and auditioning them in a five-column spatial grid.

**The current workflow generates audio first, then plays saved files.** Visitor movement controls playback; it does not make a live API request. The studio and grid are separate local services.

| Service | Address | Purpose |
| --- | --- | --- |
| Sound Studio | <http://127.0.0.1:7860/> | Generate, audition, loop, and connect two recordings |
| Spatial Grid | <http://127.0.0.1:8000/> | Move between five saved music cells with playback crossfades |

## Set up

Run commands from the repository root. Use Python 3.10 or later.

On macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

On Windows PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

If activation is blocked, use `.\.venv\Scripts\python.exe` in place of `python`.

Create `.env` in the repository root:

```dotenv
STABILITY_API_KEY=your_stability_api_key
```

Never commit the key. It is read by the local backend, not exposed to the browser. Generation uses your Stability account credits; local loop processing and playback do not.

Start the studio:

```bash
python studio.py
```

On macOS, you can instead double-click `打开音乐工作室.command`, which prepares dependencies and opens the studio. Keep the service terminal running.

## Transition workflow: from two paintings to five cells

```text
Generate A and B → curate their loops
                         ↓
A ending + masked interval + B beginning
                         ↓
             Stability inpainting
                         ↓
       Listen and select a good middle excerpt
                         ↓
    Two audio-to-audio variations of that excerpt
                         ↓
 A | A-leaning | curated middle | B-leaning | B
                         ↓
          Spatial playback crossfades
```

There are three different operations here:

| Operation | What it does | When it runs |
| --- | --- | --- |
| **Inpainting** | Generates a bridge with actual A and B audio on either side as context | Preparation; one paid request per candidate |
| **Audio-to-audio**, called `transition()` in the code | Reinterprets one input excerpt according to a prompt | Preparation; two paid requests to build the interior variations |
| **Playback crossfade** | Fades the outgoing cell down and incoming cell up | Locally while the visitor moves; no generation |

### 1. Generate and prepare the two endpoint loops

In the studio, enter the artwork name, prompt, duration and output format. Prefer WAV for editing. Generate candidates and choose one for each painting.

New recordings use names such as `Mondrian-001.wav`, with numbers allocated per artwork. The **Loop-oriented** option adds structural guidance to the prompt; it does not guarantee a seamless file.

In **Your listening room → 循环接缝处理**:

1. Choose the head/tail overlap, for example 1 second.
2. Process the loop and audition its wrap several times.
3. Use **用此 Loop 作为 A** for the starting painting, and **用此 Loop 作为 B** for the destination. Original recordings also have A/B buttons.

Loop processing is local and leaves the original unchanged. A 30-second recording with a 1-second overlap becomes 29 seconds. This removes a waveform discontinuity but does not automatically align beats or harmonies. All overlap settings must be shorter than half the source duration.

Completed recordings and processed loops appear in the transition source list automatically. **Between two paintings** is the last section of the studio, after generation, listening and loop preparation.

### 2. Generate a connecting passage with inpainting

In **Between two paintings**, choose the prepared A/B loops. The starting settings are:

- A context: its last **8 seconds**.
- New bridge: **12 seconds**.
- B context: its first **8 seconds**.

The 28-second reference consists of `A[8s] + silence[12s] + B[8s]`. The silent middle is the generation mask. The optional musical-direction field supplements a default connecting-passage prompt.

The automated pipeline in `transition_builder.py`:

1. Converts the selected context to 44.1 kHz stereo.
2. Submits the reference and middle mask to Stability inpainting.
3. Waits for the complete generated result.
4. Restores the original A/B context outside the middle, blending over 50 ms at each join.
5. Exports the full transition and a separate bridge with 50 ms of join allowance on each side. If necessary, the assembled output receives a common gain reduction to prevent clipping.

For the default settings, listen especially to **8–20 seconds** in the full transition. The separate bridge export is **12.1 seconds**, including its join allowances.

You can also run the same workflow from the terminal:

```bash
python transition_builder.py --a "audio/painting-a-loop.wav" --b "audio/painting-b-loop.wav" --context 8 --bridge 12 --output-dir assets/generated/bridge-candidate-01
```

Replace the two input paths with real recordings. Add `--prompt "Your musical direction"` to steer the bridge. Add `--prepare-only` to create the reference and plan without a paid request. Use a new output directory for each candidate to preserve previous takes.

### 3. Curate the middle state

A directional bridge is not automatically a good place to stay and listen. Audition candidates and select a passage that feels convincing as a mixture of the two paintings. It can be shorter than the generated bridge.

Record its **start and end times relative to the full transition file**. The grid builder below extracts that interval and keeps an exact original excerpt as well as a processed loop version.

This is the curator's role: choose the musical result, not just a numerical “50/50” point. Check the selected passage's loop as well as its connections to neighboring cells.

### 4. Build and install the five-cell grid

Use `curated_grid.py` with the approved endpoint loops, the full transition recording, and the selected interval:

```bash
python curated_grid.py --source "assets/generated/bridge-candidate-01/transition.wav" --start 8 --end 20 --a "audio/painting-a-loop.wav" --b "audio/painting-b-loop.wav" --output-dir assets/generated/grid-candidate-01
```

**Before using this for another pair of paintings, edit `PROMPTS` in `curated_grid.py`.** They currently describe Mondrian and Morandi. The source filenames alone do not adapt these prompts.

| Grid column | Content | Preparation |
| --- | --- | --- |
| 0 | Approved A loop | Copied unchanged |
| 1 | A-leaning version of the curated middle | Audio-to-audio, using the middle as reference and an A-leaning prompt |
| 2 | Curated middle excerpt | Extracted from the selected recording |
| 3 | B-leaning version of the curated middle | Audio-to-audio, using the middle as reference and a B-leaning prompt |
| 4 | Approved B loop | Copied unchanged |

Columns 1 and 3 use **the middle excerpt as their audio input**, not both endpoint recordings. They are prompted variations, not mathematically interpolated mixtures. Their transformation strength is currently `0.4`.

The builder applies a 0.25-second circular crossfade to all three interior cells. A 12-second excerpt therefore produces an **11.75-second** loop; a 9-second excerpt produces an **8.75-second** loop. Endpoints retain their existing loop processing.

After generation and validation, the builder installs `audio/cell_0.wav` through `audio/cell_4.wav` and writes `audio/grid_manifest.json`. The output directory retains the raw generations, original middle excerpt, plan, manifest, and a `previous-grid/` backup of the replaced files.

**Use a fresh output directory whenever inputs, prompts or timing change.** Existing `cell_1-raw.wav` and `cell_3-raw.wav` in that directory are reused rather than submitted again. A normal new run uses two paid generations in addition to the earlier inpainting request. Installation replaces the active grid, so run one grid build at a time.

### 5. Audition the grid

Start the grid in a second terminal with the same Python environment:

```bash
python -m uvicorn server:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/>, start playback, and move the X control through the five columns. After replacing audio, reload the page so it loads the new files.

The grid prefers WAV cells and falls back to the original MP3 cells. X chooses a column; **Y currently does not change the audio**. Crossing a column boundary starts its track and crossfades between the outgoing and incoming players. The default fade is 3 seconds and is adjustable. It does not continuously interpolate a generated musical representation or synchronize the cells' beats/playheads.

Listen while moving both ways, stopping in each cell and crossing boundaries slowly and quickly. A smooth volume envelope can still conceal an awkward musical change; judge both the loop and the transition by ear.

## Current Mondrian → Morandi example

The latest installed grid uses:

| Role | Local source |
| --- | --- |
| A | `assets/generated/Mondrian-Boogie-Revival-loop-44100.wav` — 29 seconds, 1-second loop overlap |
| B | `assets/generated/754b73fa-411e-46c2-806d-26a3dcbd94ad-loop-220500.wav` — 27 seconds, 5-second loop overlap |
| Inpainted transition | `assets/generated/fef122da-674a-486f-840d-4781a408cc33.wav` — 28 seconds |
| Selected middle | Seconds **8–20** of that transition |
| Grid generation records and previous-grid backup | `assets/generated/curated-grid-boogie-revival-20261021/` |

The five active durations are **29 / 11.75 / 11.75 / 11.75 / 27 seconds**. Check `audio/grid_manifest.json` for the active source paths, prompts, excerpt interval and file hashes; subsequent builds change these values.

## What can improve the musical transition?

Current technical checks cover file validity, duration and export levels. They do not assess musical compatibility. Neither BPM in a prompt nor the word “loop” guarantees beat alignment.

A next experiment is to reduce rhythmic density before changing speed: keep the opening pulse, thin the attacks into a half-time feel, then let sparse notes and sustained tones approach the destination. Manually select musically useful reference boundaries and durations. **Automatic tempo detection, beat/phrase alignment and this rhythmic-transition strategy are not implemented in the current grid.**

We have also generated separate Mondrian piano, rhythmic-accent and sustained-harmony candidates. These are independently generated parts, not synchronized stems extracted from one performance. They still require compatibility checks and alignment. The combined previews are experiments; **they are not used by the current five-cell grid**. A future layered player could fade rhythmic and melodic parts independently while keeping a compatible background active.

## Sharing the work with collaborators

- Commit source code and documentation; keep `.env` private.
- `assets/generated/` is Git-ignored. A fresh clone does **not** contain the studio history, example sources, or generation backups listed above. Share the approved audio and its plan/manifest separately, then have collaborators use their local paths.
- Grid manifests contain machine-specific absolute source paths. They document provenance; collaborators need the actual recordings to rebuild.
- The studio allows one generation job at a time and does not automatically retry paid requests. If a connection times out or the service restarts during generation, check the Stability account before submitting again.
- Changing the studio source code requires a service restart; wait until any generation finishes first.

## Earlier terminal mixer demo

The separate `gallery_engine.py` demo uses the `storm`, `machine` and `dream` layers in `gallery.json`:

```bash
python make_demo_assets.py
python gallery_engine.py
```

Type an artwork name to switch, or `q` to quit. These synthesized placeholder layers and this terminal mixer are separate from the Mondrian/Morandi browser grid. The terminal mixer loads WAVs at startup; restart it after replacing its assets.

If needed, inspect audio devices with:

```bash
python -c "import sounddevice as sd; print(sd.query_devices())"
```
