import tempfile
from pathlib import Path
import unittest

import numpy as np
import soundfile as sf

from loop_processing import crossfade_loop, export_loop


class LoopProcessingTests(unittest.TestCase):
    def test_large_original_wrap_becomes_adjacent_sample_transition(self):
        source = np.linspace(-0.8, 0.8, 1000, dtype=np.float32)
        before = source.copy()
        result, overlap = crossfade_loop(source, 1000, 0.1)
        self.assertEqual(overlap, 100)
        self.assertEqual(len(result), 900)
        self.assertLess(abs(result[-1] - result[0]), 0.002)
        self.assertGreater(abs(source[-1] - source[0]), 1.5)
        np.testing.assert_array_equal(source, before)

    def test_correlated_stereo_does_not_gain_or_dip(self):
        source = np.tile(np.array([0.25, -0.5], dtype=np.float32), (1000, 1))
        result, _ = crossfade_loop(source, 1000, 0.2)
        self.assertEqual(result.shape, (800, 2))
        np.testing.assert_allclose(result, np.tile([0.25, -0.5], (800, 1)), atol=1e-7)

    def test_invalid_overlap_and_invalid_samples_are_rejected(self):
        source = np.ones((100, 2), dtype=np.float32)
        for seconds in [0, -1, float("nan"), float("inf"), 11, 0.05, 0.06, 0.0001]:
            with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                crossfade_loop(source, 1000, seconds)
        source[0, 0] = np.nan
        with self.assertRaises(ValueError):
            crossfade_loop(source, 1000, 0.01)

    def test_export_preserves_source_rate_channels_and_original(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "original.wav"
            sf.write(source, np.ones((8000, 2), dtype=np.float32) * 0.1, 8000)
            original = source.read_bytes()
            result = export_loop(source, directory, "test", 0.25)
            output = Path(directory) / "test-loop-2000.wav"
            info = sf.info(output)
            self.assertEqual(info.frames, 6000)
            self.assertEqual(info.samplerate, 8000)
            self.assertEqual(info.channels, 2)
            self.assertEqual(info.subtype, "PCM_24")
            self.assertEqual(result["duration"], 0.75)
            self.assertEqual(result["source_duration"], 1)
            self.assertEqual(source.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
