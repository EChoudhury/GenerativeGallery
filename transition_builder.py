"""Automated, two-sided music bridge generation with Stable Audio inpainting."""

import argparse
from fractions import Fraction
import json
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly
import soundfile as sf

from generate_assets import StabilityAudioClient

SAMPLE_RATE = 44100
DEFAULT_PROMPT = (
    "Create an instrumental connecting passage in the masked middle interval. "
    "Use the supplied opening AND ending audio as musical references. "
    "Continue the opening's phrasing, then gradually introduce the ending's "
    "timbre, harmonic atmosphere, and rhythmic character. If the rhythms differ, "
    "thin the pulse into a sparse shared texture before establishing the ending's groove. "
    "Keep perceived loudness and acoustic space continuous. Approach the ending "
    "reference naturally. No vocals, dramatic climax, final cadence, fade to silence, "
    "or repeating-loop structure."
)


class BridgeError(ValueError):
    """A readable local validation error; never contains provider credentials."""


def stereo_resample(audio, source_rate):
    if audio.ndim == 1:
        audio = audio[:, None]
    if audio.shape[1] == 1:
        audio = np.repeat(audio, 2, axis=1)
    elif audio.shape[1] > 2:
        audio = audio[:, :2]
    if source_rate != SAMPLE_RATE:
        ratio = Fraction(SAMPLE_RATE, source_rate)
        audio = resample_poly(audio, ratio.numerator, ratio.denominator, axis=0)
    return np.asarray(audio, dtype=np.float32)


def read_anchor(path, seconds, tail=False):
    """Read only the required head/tail; preserve pitch when resampling."""
    with sf.SoundFile(path) as source:
        frames = min(len(source), round(seconds * source.samplerate))
        if frames < 2:
            raise BridgeError("参考音频过短，请选择可播放的音乐文件。")
        if tail:
            source.seek(len(source) - frames)
        audio = source.read(frames, dtype="float32", always_2d=True)
        audio = stereo_resample(audio, source.samplerate)
    if not np.isfinite(audio).all() or np.max(np.abs(audio)) < 1e-6:
        raise BridgeError("选取的参考片段是静音或包含无效采样，请换一个音频文件。")
    return audio


def prepare_reference(source_a, source_b, directory, context_seconds=8, bridge_seconds=12,
                      prompt=""):
    if not 1 <= context_seconds <= 20 or not 1 <= bridge_seconds <= 120:
        raise BridgeError("参考片段应为 1–20 秒，中间段应为 1–120 秒。")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    a = read_anchor(source_a, context_seconds, tail=True)
    b = read_anchor(source_b, context_seconds)
    gap = round(bridge_seconds * SAMPLE_RATE)
    reference = np.concatenate([a, np.zeros((gap, 2), dtype=np.float32), b])
    if len(reference) < 6 * SAMPLE_RATE:
        raise BridgeError("拼接参考音频不足 6 秒，请增加参考片段或中间段时长。")
    # Float WAV keeps reference samples intact; maximum settings remain below 100 MB.
    sf.write(directory / "reference.wav", reference, SAMPLE_RATE, subtype="FLOAT")
    plan = {
        "source_a": str(Path(source_a).resolve()), "source_b": str(Path(source_b).resolve()),
        "sample_rate": SAMPLE_RATE, "a_frames": len(a), "b_frames": len(b),
        "bridge_frames": gap, "total_frames": len(reference),
        "mask_start": len(a) / SAMPLE_RATE,
        "mask_end": (len(a) + gap) / SAMPLE_RATE,
        "duration": len(reference) / SAMPLE_RATE,
        "bridge_seconds": gap / SAMPLE_RATE,
        "prompt": DEFAULT_PROMPT + ("\n\nAdditional musical direction: " + prompt.strip() if prompt.strip() else ""),
    }
    (directory / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return plan


def finish_bridge(directory, plan):
    """Keep original anchors and blend only near the generated interval's edges."""
    directory = Path(directory)
    reference, _ = sf.read(directory / "reference.wav", dtype="float32", always_2d=True)
    generated, rate = sf.read(directory / "generated.wav", dtype="float32", always_2d=True)
    generated = stereo_resample(generated, rate)
    expected = plan["total_frames"]
    if abs(len(generated) - expected) > SAMPLE_RATE * 0.1:
        raise BridgeError("返回音频时长与参考不匹配，未自动拼接；请检查生成文件。")
    start = plan["a_frames"]
    end = start + plan["bridge_frames"]
    if len(generated) < end:
        raise BridgeError("生成音频没有覆盖完整中间段，无法拼接。")
    if not np.isfinite(generated).all():
        raise BridgeError("生成音频包含无效采样，无法拼接。")
    if len(generated) < expected:
        generated = np.pad(generated, ((0, expected - len(generated)), (0, 0)))
    generated = generated[:expected]
    # A short overlap on each anchor prevents a new discontinuity when restoring it.
    overlap = min(round(0.05 * SAMPLE_RATE), start // 4, (expected - end) // 4)
    ramp = np.linspace(0, 1, overlap, dtype=np.float32)[:, None]
    output = reference.copy()
    output[start:end] = generated[start:end]
    output[start-overlap:start] = reference[start-overlap:start] * (1-ramp) + generated[start-overlap:start] * ramp
    output[end:end+overlap] = generated[end:end+overlap] * (1-ramp) + reference[end:end+overlap] * ramp
    peak = float(np.max(np.abs(output)))
    gain = min(1.0, 0.98 / peak) if peak else 1.0
    output *= gain
    sf.write(directory / "transition.wav", output, SAMPLE_RATE, subtype="PCM_24")
    sf.write(directory / "bridge.wav", output[start-overlap:end+overlap], SAMPLE_RATE, subtype="PCM_24")
    middle = output[start:end]
    report = {
        "duration": len(output) / SAMPLE_RATE,
        "bridge_seconds": plan["bridge_seconds"],
        "bridge_export_seconds": len(middle) / SAMPLE_RATE + 2 * overlap / SAMPLE_RATE,
        "seam_overlap_seconds": overlap / SAMPLE_RATE,
        "peak_before_gain": peak, "output_gain": gain,
        "middle_rms": float(np.sqrt(np.mean(middle.astype(np.float64) ** 2))),
        "warnings": [],
    }
    if report["middle_rms"] < 0.0001:
        report["warnings"].append("中间段音量很低，请试听确认是否存在明显静音。")
    if gain < 1:
        report["warnings"].append("为避免导出削波，已对整段统一降低音量。")
    report["warnings"].append("技术检查不评价音乐匹配度；未自动检测或对齐节拍、调性。")
    (directory / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def build_transition(source_a, source_b, directory, context_seconds=8, bridge_seconds=12,
                     prompt="", client=None, on_status=None, prepare_only=False):
    if on_status:
        on_status("preparing")
    plan = prepare_reference(source_a, source_b, directory, context_seconds, bridge_seconds, prompt)
    if prepare_only:
        return {"plan": plan, "prepared_only": True}
    owned_client = client is None
    if owned_client:
        client = StabilityAudioClient()
    try:
        if on_status:
            on_status("submitting")
        client.inpaint(
            Path(directory) / "reference.wav", plan["prompt"],
            Path(directory) / "generated.wav", duration=plan["duration"],
            mask_start=plan["mask_start"], mask_end=plan["mask_end"], on_status=on_status,
        )
        if on_status:
            on_status("assembling")
        report = finish_bridge(directory, plan)
        return {"plan": plan, "report": report}
    finally:
        if owned_client:
            client.session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--a", required=True)
    parser.add_argument("--b", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--context", type=float, default=8)
    parser.add_argument("--bridge", type=float, default=12)
    parser.add_argument("--prompt", default="")
    parser.add_argument("--prepare-only", action="store_true", help="Prepare locally without a paid API request")
    args = parser.parse_args()
    result = build_transition(args.a, args.b, args.output_dir, args.context, args.bridge,
                              args.prompt, prepare_only=args.prepare_only, on_status=print)
    print(json.dumps(result, ensure_ascii=False, indent=2))
