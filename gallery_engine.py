"""Continuous WAV layer mixer with smoothed artwork transitions."""
from pathlib import Path
import json
import threading
import time

import numpy as np
import sounddevice as sd
import soundfile as sf
from scipy.signal import resample_poly

CONFIG_PATH = Path("gallery.json")
CROSSFADE_SECONDS = 2.5
MASTER_GAIN = 0.65

def load_config():
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)

def load_audio(path: Path, target_sr: int, channels: int) -> np.ndarray:
    if not path.exists():
        raise FileNotFoundError(
            f"Missing audio file: {path}\nRun `python make_demo_assets.py` first."
        )
    audio, sr = sf.read(path, dtype="float32", always_2d=True)
    if sr != target_sr:
        # Rational resampling avoids changing pitch when assets have another sample rate.
        from math import gcd
        g = gcd(sr, target_sr)
        audio = resample_poly(audio, target_sr // g, sr // g, axis=0).astype(np.float32)
    if channels == 1:
        audio = audio.mean(axis=1, keepdims=True)
    elif audio.shape[1] == 1:
        audio = np.repeat(audio, 2, axis=1)
    elif audio.shape[1] > channels:
        audio = audio[:, :channels]
    elif audio.shape[1] < channels:
        audio = np.repeat(audio[:, :1], channels, axis=1)
    if len(audio) == 0:
        raise ValueError(f"Audio file is empty: {path}")
    return np.ascontiguousarray(audio, dtype=np.float32)

class GalleryMixer:
    def __init__(self, config):
        self.sr = int(config.get("sample_rate", 44100))
        self.channels = int(config.get("channels", 2))
        self.artworks = config["artworks"]
        self.layers = []
        self.artwork_layers = {}
        self.current_artwork = None
        self.lock = threading.Lock()
        self.running = False

        for artwork, data in self.artworks.items():
            indices = []
            for layer in data["layers"]:
                idx = len(self.layers)
                audio = load_audio(Path(layer["file"]), self.sr, self.channels)
                self.layers.append({
                    "name": f"{artwork}:{Path(layer['file']).stem}",
                    "audio": audio,
                    "position": 0,
                    "base_gain": float(layer.get("gain", 0.3)),
                    "gain": 0.0,
                    "target_gain": 0.0,
                })
                indices.append(idx)
            self.artwork_layers[artwork] = indices

    def select_artwork(self, artwork):
        if artwork not in self.artwork_layers:
            print(f"Unknown artwork {artwork!r}. Choose: {', '.join(self.artwork_layers)}")
            return
        with self.lock:
            self.current_artwork = artwork
            for i, layer in enumerate(self.layers):
                belongs = i in self.artwork_layers[artwork]
                layer["target_gain"] = layer["base_gain"] if belongs else 0.0
        print(f"Transitioning to: {artwork}")

    def callback(self, outdata, frames, time_info, status):
        if status:
            # Audio status warnings can indicate under-runs; keep callback lightweight.
            pass
        out = np.zeros((frames, self.channels), dtype=np.float32)
        ramp = min(1.0, frames / max(1.0, self.sr * CROSSFADE_SECONDS))
        with self.lock:
            for layer in self.layers:
                audio = layer["audio"]
                pos = layer["position"]
                length = len(audio)
                # Loop the file, including when the callback crosses its end.
                first = min(frames, length - pos)
                chunk = np.empty((frames, self.channels), dtype=np.float32)
                chunk[:first] = audio[pos:pos + first]
                if first < frames:
                    chunk[first:] = audio[:frames - first]
                layer["position"] = (pos + frames) % length

                # Smooth gain changes over several callbacks.
                old_gain = layer["gain"]
                target = layer["target_gain"]
                gains = np.linspace(old_gain, target, frames, dtype=np.float32)
                out += chunk * gains[:, None]
                layer["gain"] = float(gains[-1]) if frames else target
        out *= MASTER_GAIN
        np.clip(out, -0.98, 0.98, out=out)
        outdata[:] = out

    def run(self):
        self.running = True
        print("Audio engine ready. Type an artwork name to switch, or q to quit.")
        print("Artworks:", ", ".join(self.artwork_layers))
        try:
            with sd.OutputStream(
                samplerate=self.sr,
                channels=self.channels,
                dtype="float32",
                blocksize=1024,
                callback=self.callback,
            ):
                while self.running:
                    try:
                        command = input("> ").strip().lower()
                    except EOFError:
                        break
                    if command in {"q", "quit", "exit"}:
                        break
                    if command:
                        self.select_artwork(command)
        except Exception as exc:
            print("\nAudio engine failed:", repr(exc))
            print("Check that an output device is available and that the WAV assets exist.")
            raise
        finally:
            self.running = False

def main():
    config = load_config()
    mixer = GalleryMixer(config)
    # Begin with silence; select an artwork to start the sound.
    mixer.run()

if __name__ == "__main__":
    main()
