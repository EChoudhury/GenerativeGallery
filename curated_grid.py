"""Build a five-cell gallery from curated endpoints and a selected middle excerpt."""
import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import soundfile as sf

from generate_assets import StabilityAudioClient
from loop_processing import crossfade_loop

ROOT = Path(__file__).resolve().parent
PROMPTS = {
    1: """A repeating instrumental chamber-jazz texture halfway between the supplied quiet chamber excerpt and an energetic Mondrian boogie-woogie piano piece. Preserve the reference's recognizable piano phrasing, harmonic atmosphere and intimate acoustic space. Introduce a gentle regular pulse around 90 BPM, lightly swung short piano figures and a restrained repeating left-hand bass. A few warm muted-trumpet accents and rounded vibraphone notes answer the piano. Moderate activity with audible space between motifs; more rhythmic than the reference but less busy than full boogie-woogie. A stable texture throughout, no abrupt switches between styles. Warm acoustic timbres, controlled dynamics, no percussion or vocals, no intro, outro, final cadence, dramatic build or fade. Begin and end within the same ongoing groove, suitable for circular looping.""",
    3: """A repeating intimate ambient chamber texture halfway between the supplied chamber excerpt and the patient stillness of a Morandi still life. Preserve the reference's recognizable piano phrasing, harmonic atmosphere and intimate acoustic space. Relax the pulse toward 65 BPM, progressively space out the piano's small recurring figures, with soft warm sustained viola and a few rounded clarinet tones. Very restrained activity with generous space between notes, gently suspended consonant harmonies and soft natural decay. A stable texture throughout, no abrupt switches between styles. Quiet even dynamics, no percussion or vocals, no intro, outro, final cadence, dramatic build or fade. Begin and end within the same ongoing texture, suitable for circular looping.""",
}


def build_grid(source, endpoint_a, endpoint_b, output_dir, start=16, end=25,
               strength=0.4, overlap=0.25):
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    audio, sr = sf.read(source, dtype="float32", always_2d=True)
    if not 0 <= start < end <= len(audio) / sr:
        raise ValueError("Excerpt is outside the source recording")
    middle = audio[round(start * sr):round(end * sr)]
    if not np.isfinite(middle).all() or np.max(np.abs(middle)) == 0:
        raise ValueError("Invalid or silent middle excerpt")
    excerpt = output_dir / f"middle-{start:g}-{end:g}s-original.wav"
    sf.write(excerpt, middle, sr, subtype="PCM_24")
    plan = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": str(Path(source).resolve()), "excerpt_seconds": [start, end],
        "endpoint_a": str(Path(endpoint_a).resolve()),
        "endpoint_b": str(Path(endpoint_b).resolve()),
        "method": "audio-to-audio variations of the curated middle, biased toward each endpoint",
        "strength": strength, "loop_overlap_seconds": overlap,
        "prompts": PROMPTS, "cells": [],
    }
    (output_dir / "plan.json").write_text(json.dumps(plan, indent=2))
    client = None
    for index in (1, 3):
        raw = output_dir / f"cell_{index}-raw.wav"
        if not raw.exists():
            if client is None:
                client = StabilityAudioClient(poll_interval=5)
            print(f"Generating cell {index} from the curated excerpt", flush=True)
            client.transition(excerpt, PROMPTS[index], raw, duration=end-start,
                              strength=strength)
        data, rate = sf.read(raw, dtype="float32", always_2d=True)
        if abs(len(data)/rate - (end-start)) > 0.2:
            raise ValueError(f"Unexpected generated duration for cell {index}")
        if not np.isfinite(data).all() or np.max(np.abs(data)) == 0:
            raise ValueError(f"Invalid generated audio for cell {index}")
        loop, _ = crossfade_loop(data, rate, overlap)
        sf.write(output_dir / f"cell_{index}.wav", loop, rate, subtype="PCM_24")
    loop, _ = crossfade_loop(middle, sr, overlap)
    sf.write(output_dir / "cell_2.wav", loop, sr, subtype="PCM_24")
    shutil.copy2(endpoint_a, output_dir / "cell_0.wav")
    shutil.copy2(endpoint_b, output_dir / "cell_4.wav")
    for index in range(5):
        path = output_dir / f"cell_{index}.wav"
        data, rate = sf.read(path, dtype="float32", always_2d=True)
        if not np.isfinite(data).all():
            raise ValueError(f"Invalid cell {index}")
        plan["cells"].append({"column": index, "file": path.name,
            "duration": len(data)/rate, "sample_rate": rate,
            "peak": float(np.max(np.abs(data))),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    target = ROOT / "audio"
    backup = output_dir / "previous-grid"
    backup.mkdir(exist_ok=True)
    for name in [f"cell_{i}.{ext}" for i in range(5) for ext in ("wav", "mp3")] + ["grid_manifest.json"]:
        path = target / name
        if path.exists() and not (backup / name).exists():
            shutil.copy2(path, backup / name)
    # Generate and validate all five files before activating the new grid.
    for index in range(5):
        staged = target / f"cell_{index}.wav.tmp"
        shutil.copy2(output_dir / f"cell_{index}.wav", staged)
        staged.replace(target / f"cell_{index}.wav")
    plan["backup"] = str(backup)
    report = json.dumps(plan, indent=2)
    (output_dir / "manifest.json").write_text(report)
    (target / "grid_manifest.json").write_text(report)
    print("Installed five curated cells; original grid backed up at " + str(backup), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--a", required=True)
    parser.add_argument("--b", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--start", type=float, default=16)
    parser.add_argument("--end", type=float, default=25)
    args = parser.parse_args()
    build_grid(args.source, args.a, args.b, args.output_dir, start=args.start, end=args.end)
