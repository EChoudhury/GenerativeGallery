"""Audio preparation for loops and five-cell galleries."""
from fractions import Fraction
from pathlib import Path
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

RATE = 44100


def read(path):
    data, rate = sf.read(path, dtype='float32', always_2d=True)
    if not len(data) or not np.isfinite(data).all():
        raise ValueError('The audio is empty or has invalid samples.')
    if data.shape[1] == 1:
        data = np.repeat(data, 2, axis=1)
    elif data.shape[1] > 2:
        data = data[:, :2]
    if rate != RATE:
        ratio = Fraction(RATE, rate)
        data = resample_poly(data, ratio.numerator, ratio.denominator, axis=0).astype('float32')
    return data


def write(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    if not np.isfinite(data).all():
        raise ValueError('Invalid audio samples.')
    peak = float(np.max(np.abs(data)))
    gain = min(1.0, 0.98 / peak) if peak else 1
    sf.write(path, data * gain, RATE, subtype='PCM_24')
    return {'duration': len(data) / RATE, 'sample_rate': RATE, 'channels': 2, 'gain': gain}


def circular_loop(data, seconds):
    frames = round(seconds * RATE)
    if not np.isfinite(seconds) or frames < 2 or seconds > 10 or frames * 2 >= len(data):
        raise ValueError('Choose an overlap greater than zero, at most 10 seconds, and shorter than half the excerpt.')
    ramp = np.linspace(0, 1, frames, dtype='float32')[:, None]
    return np.concatenate([data[frames:-frames], data[-frames:] * (1-ramp) + data[:frames] * ramp])


def make_loop(source, output, overlap, start=0, end=None):
    data = read(source)
    end = len(data) / RATE if end is None else end
    if not 0 <= start < end <= len(data)/RATE + 1/RATE:
        raise ValueError('The selected excerpt falls outside the recording.')
    selected = data[round(start*RATE):round(end*RATE)]
    result = write(output, circular_loop(selected, overlap))
    return {**result, 'start': start, 'end': end, 'overlap': overlap, 'source_duration': len(data)/RATE}


def prepare_bridge(a, b, directory, context, bridge):
    left, right = read(a), read(b)
    left, right = left[-round(context*RATE):], right[:round(context*RATE)]
    if min(np.max(np.abs(left)), np.max(np.abs(right))) < 1e-6:
        raise ValueError('One of the selected audio anchors is silent.')
    middle = np.zeros((round(bridge*RATE), 2), dtype='float32')
    reference = np.concatenate([left, middle, right])
    if len(reference) < 6*RATE:
        raise ValueError('The reference must be at least 6 seconds long.')
    path = Path(directory) / 'reference.wav'
    sf.write(path, reference, RATE, subtype='FLOAT')
    return {'start': len(left)/RATE, 'end': (len(left)+len(middle))/RATE,
            'duration': len(reference)/RATE, 'path': str(path)}


def finish_bridge(directory, plan):
    directory = Path(directory)
    source = read(directory / 'reference.wav')
    generated = read(directory / 'generated.wav')
    if abs(len(generated)-len(source)) > RATE * 0.1:
        raise ValueError('The generated duration does not match the reference; the bridge was not installed.')
    if len(generated) < len(source):
        generated = np.pad(generated, ((0, len(source)-len(generated)), (0, 0)))
    generated = generated[:len(source)]
    start, end = round(plan['start']*RATE), round(plan['end']*RATE)
    overlap = min(round(.05*RATE), start//4, (len(source)-end)//4)
    if np.sqrt(np.mean(generated[start:end].astype('float64')**2)) < 1e-5:
        raise ValueError('The generated bridge is effectively silent; choose another candidate.')
    output = source.copy()
    output[start:end] = generated[start:end]
    ramp = np.linspace(0, 1, overlap, dtype='float32')[:, None]
    output[start-overlap:start] = source[start-overlap:start]*(1-ramp) + generated[start-overlap:start]*ramp
    output[end:end+overlap] = generated[end:end+overlap]*(1-ramp) + source[end:end+overlap]*ramp
    report = write(directory/'transition.wav', output)
    write(directory/'bridge.wav', output[start-overlap:end+overlap])
    return {**report, 'start': plan['start'], 'end': plan['end'], 'join_overlap': overlap/RATE}
