# Curator’s Gallery — local music generation platform

A complete local workbench: upload an artwork, get an editable DeepSeek music prompt, generate music with Stability, prepare and name a loop, select two saved loops, generate a five-cell gallery, and listen while moving between the artworks.

## Start on your Mac

From the repository root:

```bash
python3 -m venv .venv  # only if the environment does not already exist
.venv/bin/python -m pip install -r curator_platform/requirements.txt
.venv/bin/python -m curator_platform.app --port 7870
```

Open <http://127.0.0.1:7870/>. Alternatively, double-click `打开策展工作台.command` in the repository root. Keep the service terminal running. This app is separate from the previous studio on port 7860 and grid on port 8000; it does not replace their audio.

Configure provider keys in the repository’s root `.env` (see `.env.example`):

```dotenv
STABILITY_API_KEY=your_stability_key
DEEPSEEK_API_KEY=your_deepseek_key
DEEPSEEK_MODEL=deepseek-flash
```

Keys are read on each request. After updating `.env`, use **Connections & setup → Check connections**. This checks whether keys are configured; validity is checked by the provider when you make a request. Keys are not returned to the browser. Never commit `.env`.

DeepSeek’s current [vision API](https://api-docs.deepseek.com/guides/vision/) accepts the uploaded image alongside the artwork title, artist and curator notes. The backend requests visual/formal analysis, a contextual interpretation, three visual-to-musical mappings, and a final editable music prompt. It does not automatically look up provenance or verify art history. The requested model can be overridden with `DEEPSEEK_MODEL`, but must support image input. Without a DeepSeek key, you can still upload an artwork and write a music prompt manually.

## The workflow

1. **Create a sound.** Upload a JPG, PNG or WebP under 8 MB, enter the artwork title and artist, and optionally add curator notes. Click **Use this artwork**. If you change artwork information later, save it again before generating.
2. **Interpret artwork.** DeepSeek receives the prepared image and your metadata. Read the interpretation, edit the music prompt, and choose the generation duration. A prompt’s requested tempo, key and looping behavior are musical targets, not guarantees.
3. **Generate music.** Stability produces a complete WAV recording. The edited prompt is saved with it. Completed recordings can be reopened in **Recent generations**.
4. **Create and save a loop.** Choose the excerpt’s start/end and a head/tail overlap, audition the result, then enter a music name and save it to the library. Local processing preserves the source recording. A 16-second excerpt with a 1-second overlap becomes a 15-second loop. The overlap must be shorter than half the excerpt.
5. **Music library.** Listen, search, rename or download saved recordings. The saved name is also used for the numbered file, such as `Artwork name-001.wav`. Select two loops: the first is A, the second is B. Click **Connect these artworks**. If the approved earlier Mondrian and Morandi loop files exist on this Mac, they are copied into an initially empty library as imported recordings; no generation is needed for this import.
6. **Between artworks.** Choose reference and bridge lengths, plus optional musical direction. Either generate the entire five-cell grid, or preview the bridge first and curate its middle before building the grid.
7. **Listening grid.** Start listening. Move the position slider or click a cell to blend neighboring musical states. All five loops run on a shared playback clock. Position changes their gains with equal-power interpolation and an adjustable smoothing time; it does not restart the files at every boundary. This preserves playheads, but does not beat-match the independently generated cells.

## How the transition and five cells are built

The default reference is **A’s last 8 seconds + 12 seconds of silence + B’s first 8 seconds**. Stability inpaints the silent interval. The backend restores the original reference ends and uses 50 ms joins to assemble an audition file.

**The two reference ends are excluded from the middle cell.** In the 28-second audition, only **8–20 seconds** supplies the center. If the reference clips are shorter than 8 seconds, the actual mask timestamps are used. Preview mode shows these boundaries and only accepts an excerpt inside the generated interval, at least 4 seconds long.

| Cell | Source |
| --- | --- |
| 1 / A | Saved A loop, copied unchanged |
| 2 / A-leaning | Inpainting between A and the extracted middle; optional original mode uses audio-to-audio |
| 3 / Middle | Extracted generated interval, with the reference ends removed |
| 4 / B-leaning | Inpainting between the extracted middle and B; optional original mode uses audio-to-audio |
| 5 / B | Saved B loop, copied unchanged |

The three interior cells receive a 0.25-second circular crossfade. A 12-second middle becomes an 11.75-second loop. Each grid keeps its own recordings and manifest; a failed task does not publish a partially generated grid or replace an existing one.

Prompts for the bridge and two variations are derived from the selected recordings’ saved prompts and your transition direction; they are not hardcoded to Mondrian/Morandi. In the original hybrid mode, the two variations use the middle excerpt as their audio reference, not two simultaneous endpoint inputs. They are prompted interpretations, not mathematical mixtures.

### Inpainting-only mode

Choose **Interior cell generation → Inpainting only** to avoid audio-to-audio entirely. It uses three sequential inpaint requests:

1. A ending → masked interval → B beginning produces the shared middle.
2. A ending → masked interval → shared middle beginning produces the A-side cell.
3. Shared middle ending → masked interval → B beginning produces the B-side cell.

Every interior cell keeps **only its masked/generated interval**, removes both reference ends, and receives the same 0.25-second loop overlap. Endpoints are copied unchanged. For an existing curated bridge preview, only steps 2–3 are needed. The original hybrid method remains available for comparison, and each saved grid records its `method` (`inpaint` or `hybrid`). This provides two-sided audio context for every generated cell; it still does not guarantee natural musical transitions or beat matching.

The selector initially favors inpainting-only; older grids without a `method` field retain their original hybrid interpretation. API clients can set `method: "inpaint"` on grid tasks; omission preserves the original hybrid behavior.

### Provider requests and costs

| Action | Requests |
| --- | --- |
| Interpret artwork | 1 DeepSeek image/text request |
| Generate music | 1 Stability text-to-audio request |
| Process loop, save, rename, listen | Local only |
| Preview bridge | 1 Stability inpaint request |
| Generate full grid directly — inpainting only | 3 Stability inpaint requests |
| Generate full grid directly — original hybrid | 1 Stability inpaint + 2 audio-to-audio requests |
| Build grid from an existing bridge preview | 2 inpaint or 2 audio-to-audio requests, according to mode; the bridge is reused |

Requests are user-triggered, one task runs at a time, and paid requests are not automatically retried. Submission IDs make an identical submission idempotent. Stability generation IDs are retained in task records. After a timeout or service restart, check your provider account before requesting another paid generation. Refreshing the page restores active task polling and saved work.

## Storage and sharing

All new runtime data lives in `curator_platform/data/`, which is Git-ignored:

- `gallery.sqlite`: artwork metadata, music library, task status and gallery history.
- `images/`: validated, resized artwork images (JPEG).
- `music/`: named library recordings.
- `jobs/<id>/`: prompts, raw results, references, bridge excerpts, grid files and manifests.

Back up the **whole data folder**, including the database, to transfer a collection to another Mac. Stop the service before copying it. Provider keys remain in each collaborator’s own root `.env`. This is a local single-workspace app; it does not provide public hosting, accounts, or multi-user access.

## Verification and limitations

Run the integration tests from the repository root:

```bash
.venv/bin/python -m unittest discover -s tests -p test_curator_platform.py -v
```

Tests use a temporary database and mocked providers, spending no API credits. They cover image upload and image-bearing DeepSeek requests, prompt editing, loop preparation, numbered naming, rename/download, library persistence, inpainting mask extraction, exactly two variation requests in hybrid mode, three inpaint requests in inpainting-only mode, reference-end exclusion for every mask, partial failure, and idempotency.

The pipeline validates audio readability, duration and finite samples. It cannot guarantee prompt adherence, instrument isolation, compatible harmony, tempo or natural musical transitions. Curator listening remains essential. All audio generation happens before playback; there is no streaming prompt-controlled generation.
