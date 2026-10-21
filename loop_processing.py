"""Prepare circular audio loops by overlapping the original tail and head."""

from pathlib import Path

import numpy as np
import soundfile as sf


def crossfade_loop(audio, sample_rate, seconds):
    """Return a loop shorter by the overlap, with complementary linear gains.

    Playback starts immediately after the overlapped head. The last samples
    approach that same point, so the file's wrap is a normal adjacent-sample
    transition rather than a jump from the original ending to its beginning.
    """
    if not np.isfinite(seconds) or not 0 < seconds <= 10:
        raise ValueError("交叉淡化时长必须大于 0 且不超过 10 秒。")
    frames = round(seconds * sample_rate)
    if frames < 2 or frames * 2 >= len(audio):
        raise ValueError("交叉淡化时长必须小于原音频的一半；请缩短重叠时间。")
    if not np.isfinite(audio).all():
        raise ValueError("音频包含无效采样，无法处理。")
    weight = np.linspace(0, 1, frames, dtype=np.float32)
    if audio.ndim == 2:
        weight = weight[:, None]
    blend = audio[-frames:] * (1 - weight) + audio[:frames] * weight
    output = np.concatenate((audio[frames:-frames], blend), axis=0)
    return output, frames


def export_loop(source, output_dir, job_id, seconds):
    audio, sample_rate = sf.read(source, dtype="float32", always_2d=True)
    output, frames = crossfade_loop(audio, sample_rate, seconds)
    destination = Path(output_dir) / f"{job_id}-loop-{frames}.wav"
    temporary = destination.with_suffix(".wav.tmp")
    try:
        sf.write(temporary, output, sample_rate, format="WAV", subtype="PCM_24")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "crossfade_seconds": frames / sample_rate,
        "source_duration": len(audio) / sample_rate,
        "duration": len(output) / sample_rate,
        "sample_rate": sample_rate,
        "channels": audio.shape[1],
        "overlap_frames": frames,
        "audio_url": f"/api/audio/{job_id}/loop/{frames}",
    }
