"""Create gentle, loopable synthetic placeholder layers for mixer testing."""
from pathlib import Path
import numpy as np
import soundfile as sf

SR = 44100
SECONDS = 12
N = SR * SECONDS
OUT = Path("assets")
OUT.mkdir(exist_ok=True)
t = np.arange(N, dtype=np.float64) / SR

def smooth_noise(seed, amount=0.025):
    rng = np.random.default_rng(seed)
    # Slowly changing noise; periodic endpoints keep the loop less abrupt.
    knots_n = 80
    knots = rng.normal(0, 1, knots_n + 1)
    knots[-1] = knots[0]
    x = np.linspace(0, knots_n, N, endpoint=False)
    noise = np.interp(x, np.arange(knots_n + 1), knots)
    noise /= max(np.max(np.abs(noise)), 1e-9)
    return amount * noise

def write(name, signal):
    signal = np.asarray(signal, dtype=np.float64)
    # Stereo with subtle channel difference
    stereo = np.column_stack([signal, np.roll(signal, 137) * 0.98])
    peak = np.max(np.abs(stereo))
    if peak > 0.88:
        stereo *= 0.88 / peak
    sf.write(OUT / name, stereo.astype(np.float32), SR, subtype="PCM_16")
    print("Wrote", OUT / name)

# Gentle slow drones, integer-cycle frequencies so they loop cleanly.
write("storm_drone.wav",
      0.16*np.sin(2*np.pi*55*t) + 0.07*np.sin(2*np.pi*82.5*t)
      + 0.025*np.sin(2*np.pi*110*t))
write("storm_texture.wav",
      0.07*np.sin(2*np.pi*330*t) * (0.5 + 0.5*np.sin(2*np.pi*t/6)**2)
      + smooth_noise(3, 0.018))
write("machine_pulse.wav",
      0.13*np.sin(2*np.pi*65.406*t) * (0.35 + 0.65*(0.5 + 0.5*np.sin(2*np.pi*2*t)))
      + 0.05*np.sin(2*np.pi*130.812*t))
write("machine_texture.wav",
      0.045*np.sin(2*np.pi*440*t) * (0.5 + 0.5*np.sin(2*np.pi*4*t))
      + smooth_noise(7, 0.012))
write("dream_pad.wav",
      0.12*np.sin(2*np.pi*261.626*t) + 0.055*np.sin(2*np.pi*392*t)
      + 0.025*np.sin(2*np.pi*523.251*t))
write("dream_texture.wav",
      0.035*np.sin(2*np.pi*659.255*t) * (0.5 + 0.5*np.sin(2*np.pi*t/8)**2)
      + smooth_noise(11, 0.009))
print("Done. These are test tones/textures; replace them with generated audio later.")
