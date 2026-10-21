import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np
import soundfile as sf

from generate_assets import StabilityAudioClient
from transition_builder import prepare_reference, finish_bridge, build_transition, BridgeError


class TransitionBuilderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.a = self.root / "a.wav"
        self.b = self.root / "b.wav"
        sf.write(self.a, np.linspace(-0.3, 0.3, 16000), 8000, subtype="FLOAT")
        sf.write(self.b, np.full((32000, 2), 0.2), 16000, subtype="FLOAT")
        self.work = self.root / "work"

    def tearDown(self):
        self.temp.cleanup()

    def test_prepare_only_crops_tail_head_resamples_and_never_calls_api(self):
        client = Mock()
        result = build_transition(self.a, self.b, self.work, 1, 4, client=client, prepare_only=True)
        client.inpaint.assert_not_called()
        plan = result["plan"]
        self.assertEqual((plan["mask_start"], plan["mask_end"], plan["duration"]), (1, 5, 6))
        reference, rate = sf.read(self.work / "reference.wav", always_2d=True)
        self.assertEqual(rate, 44100)
        self.assertEqual(reference.shape, (264600, 2))
        np.testing.assert_array_equal(reference[44100:220500], 0)
        self.assertGreater(reference[1000, 0], 0)
        self.assertAlmostEqual(reference[-1000, 0], 0.2, places=4)

    def test_full_pipeline_uses_inpaint_with_two_anchors_and_restores_them(self):
        originals = self.a.read_bytes(), self.b.read_bytes()
        stages = []
        client = Mock()
        def fake_inpaint(input_audio, prompt, output, duration, mask_start, mask_end, on_status):
            reference, rate = sf.read(input_audio, dtype="float32", always_2d=True)
            reference += 0.1  # Simulate a provider changing even the unmasked anchors.
            start, end = round(mask_start * rate), round(mask_end * rate)
            reference[start:end] = 0.1
            sf.write(output, reference, rate, subtype="FLOAT")
            on_status("generating")
            self.assertEqual((duration, mask_start, mask_end), (6, 1, 5))
        client.inpaint.side_effect = fake_inpaint
        result = build_transition(self.a, self.b, self.work, 1, 4, client=client, on_status=stages.append)
        self.assertEqual(client.inpaint.call_count, 1)
        reference, _ = sf.read(self.work / "reference.wav")
        final, rate = sf.read(self.work / "transition.wav")
        np.testing.assert_allclose(final[:40000], reference[:40000], atol=2e-7)
        np.testing.assert_allclose(final[-40000:], reference[-40000:], atol=2e-7)
        self.assertEqual(len(final), len(reference))
        self.assertEqual(sf.info(self.work / "transition.wav").subtype, "PCM_24")
        self.assertAlmostEqual(sf.info(self.work / "bridge.wav").duration, 4.1)
        self.assertIn("assembling", stages)
        self.assertEqual((self.a.read_bytes(), self.b.read_bytes()), originals)
        self.assertAlmostEqual(result["report"]["middle_rms"], 0.1, places=5)

    def test_invalid_sources_and_duration_fail_before_paid_request(self):
        silent = self.root / "silent.wav"
        sf.write(silent, np.zeros(8000), 8000)
        client = Mock()
        with self.assertRaises(BridgeError):
            build_transition(silent, self.b, self.work, client=client)
        with self.assertRaises(BridgeError):
            build_transition(self.a, self.b, self.work, 1, 1, client=client)
        client.inpaint.assert_not_called()

    def test_malformed_provider_audio_is_not_exported(self):
        plan = prepare_reference(self.a, self.b, self.work, 1, 4)
        sf.write(self.work / "generated.wav", np.ones((44100, 2)) * 0.1, 44100)
        with self.assertRaises(BridgeError):
            finish_bridge(self.work, plan)
        self.assertFalse((self.work / "transition.wav").exists())

    def test_inpaint_client_sends_documented_mask_fields_and_wav(self):
        client = StabilityAudioClient(api_key="fake-test-key")
        with patch("generate_assets.requests.post", return_value=Mock()) as request, \
             patch.object(client, "_wait_for_result", return_value=self.work / "generated.wav"):
            client.inpaint(self.a, "Connect the references", self.work / "generated.wav", 6, 1, 5)
        self.assertTrue(request.call_args.args[0].endswith("/stable-audio/inpaint"))
        self.assertEqual(request.call_args.kwargs["data"], {
            "prompt": "Connect the references", "output_format": "wav", "duration": 6,
            "mask_start": 1, "mask_end": 5,
        })
        client.session.close()
