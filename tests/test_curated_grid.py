import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import soundfile as sf

import curated_grid
import server
from generate_assets import StabilityAudioClient


class CuratedGridTests(unittest.TestCase):
    def test_install_preserves_endpoints_excerpt_and_old_grid(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'audio').mkdir()
            (root / 'audio/cell_2.mp3').write_bytes(b'old-grid')
            sr = 8000
            samples = np.sin(np.arange(30*sr)*0.12).astype('float32') * 0.1
            source = root / 'source.wav'
            sf.write(source, samples, sr, subtype='PCM_24')
            a, b = root / 'a.wav', root / 'b.wav'
            sf.write(a, samples[:sr], sr)
            sf.write(b, samples[:2*sr], sr)
            fake = Mock()
            def transition(input_audio, prompt, output, duration, strength):
                data, rate = sf.read(input_audio)
                sf.write(output, data, rate, subtype='PCM_24')
            fake.transition.side_effect = transition
            output = root / 'built'
            with patch.object(curated_grid, 'ROOT', root), patch.object(curated_grid, 'StabilityAudioClient', return_value=fake):
                curated_grid.build_grid(source, a, b, output)
            self.assertEqual(fake.transition.call_count, 2)
            self.assertEqual((root / 'audio/cell_0.wav').read_bytes(), a.read_bytes())
            self.assertEqual((root / 'audio/cell_4.wav').read_bytes(), b.read_bytes())
            original, _ = sf.read(source)
            excerpt, _ = sf.read(output / 'middle-16-25s-original.wav')
            np.testing.assert_array_equal(excerpt, original[16*sr:25*sr])
            self.assertEqual(sf.info(root / 'audio/cell_2.wav').duration, 8.75)
            self.assertEqual((output / 'previous-grid/cell_2.mp3').read_bytes(), b'old-grid')

    def test_server_prefers_wav_with_correct_type_and_mp3_fallback(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(server, 'AUDIO_DIR', Path(directory)):
            path = Path(directory)
            (path / 'cell_0.mp3').touch()
            self.assertEqual(server.stream_audio(0).media_type, 'audio/mpeg')
            (path / 'cell_0.wav').touch()
            self.assertEqual(server.get_audio_path(0).suffix, '.wav')
            self.assertEqual(server.stream_audio(0).media_type, 'audio/wav')
            routes = [r for r in server.app.routes if getattr(r, 'path', '').startswith('/audio/')]
            matches = [r for r in routes if r.path_regex.match('/audio/drone')]
            self.assertEqual([r.name for r in matches], ['stream_drone'])

    def test_transition_requests_wav(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'input.wav'
            source.touch()
            client = StabilityAudioClient(api_key='test')
            with patch('generate_assets.requests.post') as post, patch.object(client, '_wait_for_result') as wait:
                client.transition(source, 'prompt', Path(directory) / 'out.wav')
                self.assertEqual(post.call_args.kwargs['data']['output_format'], 'wav')
                wait.assert_called_once()


if __name__ == '__main__':
    unittest.main()
