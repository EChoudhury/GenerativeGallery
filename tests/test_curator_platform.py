"""End-to-end local HTTP tests. All external providers are mocked; no credits spent."""
import base64
import io
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
import urllib.error
import urllib.request
import urllib.parse
import uuid

import numpy as np
from PIL import Image
import soundfile as sf
import uvicorn
from curator_platform import app as platform
from curator_platform import audio, providers


class ImmediateExecutor:
    def submit(self, function, *args):
        function(*args)


class FakeAudio:
    calls = []
    fail_variation = False

    def __init__(self, on_status=lambda value: None):
        self.on_status = on_status

    def generate(self, prompt, output, duration):
        self.calls.append(('generate', prompt, duration))
        data = np.sin(np.arange(round(duration*audio.RATE))*2*np.pi*220/audio.RATE).astype('float32')*.15
        audio.write(output, np.repeat(data[:, None], 2, axis=1))

    def inpaint(self, source, prompt, output, duration, start, end):
        self.calls.append(('inpaint', prompt, duration, start, end))
        data = audio.read(source)
        self.assert_silent_middle(data, start, end)
        data[round(start*audio.RATE):round(end*audio.RATE)] = .12
        self.on_status('remote:fake-inpaint-id')
        audio.write(output, data)

    @staticmethod
    def assert_silent_middle(data, start, end):
        assert np.max(np.abs(data[round(start*audio.RATE):round(end*audio.RATE)])) == 0

    def variation(self, source, prompt, output, duration, strength=.4):
        self.calls.append(('variation', prompt, duration))
        if self.fail_variation:
            raise providers.ProviderError('Simulated provider failure; no retry.')
        data = audio.read(source)
        assert len(data) == round(duration*audio.RATE)
        audio.write(output, data*.8)


class CuratorPlatformTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.real_audio_class = providers.AudioProvider
        cls.temp = tempfile.TemporaryDirectory()
        cls.patches = [patch.object(platform, 'DATA', Path(cls.temp.name)),
                       patch.object(platform, 'EXPORT_ROOT', Path(cls.temp.name)/'exports'),
                       patch.object(platform, 'EXECUTOR', ImmediateExecutor()),
                       patch.object(providers, 'configured', return_value={'stability': True, 'deepseek': True}),
                       patch.object(providers, 'AudioProvider', FakeAudio)]
        for item in cls.patches:
            item.start()
        platform.initialize(seed=False)
        cls.patches.append(patch.object(platform, 'initialize'))
        cls.patches[-1].start()
        cls.sock = socket.socket()
        cls.sock.bind(('127.0.0.1', 0))
        cls.base = 'http://127.0.0.1:'+str(cls.sock.getsockname()[1])
        cls.server = uvicorn.Server(uvicorn.Config(platform.app, log_level='error'))
        cls.thread = threading.Thread(target=lambda: cls.server.run(sockets=[cls.sock]), daemon=True)
        cls.thread.start()
        for _ in range(200):
            if cls.server.started:
                return
            time.sleep(.01)
        raise RuntimeError('Local test server did not start')

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.thread.join(timeout=5)
        cls.sock.close()
        for item in reversed(cls.patches):
            item.stop()
        cls.temp.cleanup()

    def setUp(self):
        with platform.connect() as db:
            db.execute('DELETE FROM records')
        FakeAudio.calls = []
        FakeAudio.fail_variation = False

    def call(self, path, body=None, method=None, headers=None):
        values = {'Origin': self.base, 'X-Curator-Request': '1', **(headers or {})}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            values['Content-Type'] = 'application/json'
        request = urllib.request.Request(self.base+path, data=data, headers=values, method=method)
        try:
            response = urllib.request.urlopen(request, timeout=20)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, response.headers, response.read()

    def json(self, path, body=None, method=None):
        status, _, content = self.call(path, body, method)
        self.assertLess(status, 300, content[:500])
        return json.loads(content)

    def artwork(self):
        image = io.BytesIO()
        Image.new('RGB', (48, 48), 'olive').save(image, format='PNG')
        return self.json('/api/artworks', {'title': 'Test Painting', 'artist': 'Test Artist',
            'notes': 'Quiet geometric forms', 'image': 'data:image/png;base64,'+base64.b64encode(image.getvalue()).decode()})

    def task(self, kind, **values):
        job = self.json('/api/jobs', {'request_id': str(uuid.uuid4()), 'kind': kind, **values})
        return self.json('/api/jobs/'+job['id'])

    def saved_pair(self):
        artwork = self.artwork()
        generated = self.task('music', artwork_id=artwork['id'], prompt='A piano motif in C', duration=16)
        self.assertEqual(generated['status'], 'completed', generated.get('error'))
        loop = self.task('loop', source_job_id=generated['id'], overlap=1, start=0, end=16)
        self.assertEqual(loop['status'], 'completed', loop.get('error'))
        self.assertEqual(loop['result']['duration'], 15)
        a = self.json('/api/music', {'request_id': str(uuid.uuid4()), 'source_job_id': loop['id'], 'name': 'Painting A'})
        b = self.json('/api/music', {'request_id': str(uuid.uuid4()), 'source_job_id': loop['id'], 'name': 'Painting B'})
        return a, b, generated, loop

    def test_upload_prompt_edit_generate_loop_save_rename_and_download(self):
        artwork = self.artwork()
        answer = {'visual_reading': 'Olive geometry', 'context_reading': 'A curator interpretation',
                  'mapping': ['Geometry → short piano cells'], 'music_prompt': 'A generated prompt in C'}
        with patch.object(providers, 'artwork_prompt', return_value=answer) as prompt:
            job = self.task('prompt', artwork_id=artwork['id'], duration=16)
            self.assertEqual(job['status'], 'completed', job.get('error'))
            self.assertEqual(job['result']['music_prompt'], answer['music_prompt'])
            self.assertTrue(prompt.call_args.args[1].is_file())
        job = self.task('music', artwork_id=artwork['id'], prompt='My edited prompt', duration=16)
        self.assertEqual(FakeAudio.calls[-1][1], 'My edited prompt')
        loop = self.task('loop', source_job_id=job['id'], overlap=1, start=2, end=14)
        self.assertEqual(loop['result']['duration'], 11)
        request = {'request_id': str(uuid.uuid4()), 'source_job_id': loop['id'], 'name': 'My painting / 花'}
        saved = self.json('/api/music', request)
        self.assertIn('My painting - 花-001.wav', saved['filename'])
        self.assertEqual(self.json('/api/music', request)['id'], saved['id'])
        renamed = self.json('/api/music/'+saved['id'], {'name': 'New name'}, 'PATCH')
        self.assertTrue(renamed['filename'].endswith('New name-001.wav'))
        self.assertFalse((platform.DATA/saved['filename']).exists())
        status, headers, content = self.call(renamed['audio_url']+'?download=true')
        self.assertEqual(status, 200)
        self.assertIn('New name-001.wav', urllib.parse.unquote(headers['Content-Disposition']))
        self.assertEqual(content[:4], b'RIFF')
        self.assertEqual(len(self.json('/api/music')), 1)
        self.assertEqual(self.json('/api/artworks/'+artwork['id'])['prompt'], 'My edited prompt')

    def test_auto_grid_cuts_both_reference_ends_and_makes_exactly_two_variations(self):
        a, b, _, _ = self.saved_pair()
        FakeAudio.calls.clear()
        grid_job = self.task('grid', a_id=a['id'], b_id=b['id'], context=8, bridge=12, name='A shared room')
        self.assertEqual(grid_job['status'], 'completed', grid_job.get('error'))
        self.assertEqual([x[0] for x in FakeAudio.calls], ['inpaint', 'variation', 'variation'])
        self.assertEqual(FakeAudio.calls[0][2:], (28.0, 8.0, 20.0))
        self.assertEqual([x[2] for x in FakeAudio.calls[1:]], [12, 12])
        grid = self.json('/api/grids/'+grid_job['result']['grid_id'])
        self.assertEqual(grid['middle_interval'], [8, 20])
        self.assertEqual([grid['files'][str(i)]['duration'] for i in range(5)], [15, 11.75, 11.75, 11.75, 15])
        self.assertEqual((platform.DATA/grid['files']['0']['file']).read_bytes(), (platform.DATA/a['filename']).read_bytes())
        middle = audio.read(platform.DATA/'jobs'/grid['id']/'middle-original.wav')
        self.assertEqual(len(middle), 12*audio.RATE)
        np.testing.assert_allclose(middle, .12, atol=1e-6)
        self.assertEqual(len(self.json('/api/grids')), 1)
        for column in range(5):
            status, _, content = self.call('/api/grids/'+grid['id']+'/audio/'+str(column))
            self.assertEqual(status, 200)
            self.assertEqual(content[:4], b'RIFF')
        self.assertEqual(self.call('/api/grids/'+grid['id']+'/audio/5')[0], 404)
        self.assertEqual(grid_job['remote_requests'][0]['id'], 'fake-inpaint-id')

    def test_inpaint_only_grid_uses_three_masks_and_excludes_all_reference_ends(self):
        a, b, _, _ = self.saved_pair()
        FakeAudio.calls.clear()
        FakeAudio.fail_variation = True  # Any audio-to-audio request would fail this task.
        job = self.task('grid', a_id=a['id'], b_id=b['id'], context=8, bridge=4, method='inpaint')
        self.assertEqual(job['status'], 'completed', job.get('error'))
        self.assertEqual([call[0] for call in FakeAudio.calls], ['inpaint']*3)
        self.assertEqual([call[2:] for call in FakeAudio.calls], [(20.0, 8.0, 12.0), (16.0, 8.0, 12.0), (16.0, 4.0, 8.0)])
        grid = self.json('/api/grids/'+job['result']['grid_id'])
        self.assertEqual(grid['method'], 'inpaint')
        for column in [1, 2, 3]:
            self.assertEqual(grid['files'][str(column)]['duration'], 3.75)
        self.assertEqual((platform.DATA/grid['files']['0']['file']).read_bytes(), (platform.DATA/a['filename']).read_bytes())
        for index in [1, 3]:
            directory = platform.DATA/'jobs'/grid['id']
            raw = audio.read(directory/f'cell_{index}-raw.wav')
            self.assertEqual(len(raw), 4*audio.RATE)
            plan = json.loads((directory/f'cell_{index}-inpaint'/'plan.json').read_text())
            self.assertEqual(plan['end']-plan['start'], 4)

    def test_inpaint_neighbors_can_reuse_a_curated_bridge_without_audio_to_audio(self):
        a, b, _, _ = self.saved_pair()
        bridge = self.task('bridge', a_id=a['id'], b_id=b['id'], context=8, bridge=12)
        FakeAudio.calls.clear()
        job = self.task('grid', source_job_id=bridge['id'], start=10, end=16, method='inpaint')
        self.assertEqual(job['status'], 'completed', job.get('error'))
        self.assertEqual([call[0] for call in FakeAudio.calls], ['inpaint', 'inpaint'])
        grid = self.json('/api/grids/'+job['result']['grid_id'])
        self.assertEqual(grid['middle_interval'], [10, 16])
        self.assertEqual(grid['files']['2']['duration'], 5.75)

    def test_bridge_preview_then_custom_excerpt_build_does_not_regenerate_bridge(self):
        a, b, _, _ = self.saved_pair()
        job = self.task('bridge', a_id=a['id'], b_id=b['id'], context=8, bridge=12)
        self.assertEqual(job['status'], 'completed', job.get('error'))
        self.assertEqual(self.call('/api/jobs/'+job['id']+'/audio?part=bridge')[0], 200)
        FakeAudio.calls.clear()
        grid_job = self.task('grid', source_job_id=job['id'], start=10, end=16)
        self.assertEqual(grid_job['status'], 'completed', grid_job.get('error'))
        self.assertEqual([x[0] for x in FakeAudio.calls], ['variation', 'variation'])
        grid = self.json('/api/grids/'+grid_job['result']['grid_id'])
        self.assertEqual(grid['middle_interval'], [10, 16])
        self.assertEqual(grid['files']['2']['duration'], 5.75)

    def test_paid_idempotency_and_failed_grid_does_not_publish_partial_cells(self):
        a, b, _, _ = self.saved_pair()
        body = {'request_id': str(uuid.uuid4()), 'kind': 'grid', 'a_id': a['id'], 'b_id': b['id']}
        FakeAudio.fail_variation = True
        self.json('/api/jobs', body)
        job = self.json('/api/jobs/'+body['request_id'])
        self.assertEqual(job['status'], 'failed')
        self.assertEqual(self.json('/api/grids'), [])
        count = len(FakeAudio.calls)
        self.json('/api/jobs', body)
        self.assertEqual(len(FakeAudio.calls), count)
        self.assertIsNotNone(job.get('bridge_result'))
        self.assertEqual(self.call('/api/jobs/'+job['id']+'/audio')[0], 200)

    def test_missing_keys_invalid_image_and_cross_origin_do_not_call_providers(self):
        with patch.object(providers, 'configured', return_value={'deepseek': False, 'stability': False}):
            self.assertEqual(self.call('/api/jobs', {'request_id': str(uuid.uuid4()), 'kind': 'prompt'})[0], 503)
        self.assertEqual(self.call('/api/artworks', {'title': 'A', 'artist': 'B', 'image': 'not-an-image'})[0], 422)
        body = {'request_id': str(uuid.uuid4()), 'kind': 'grid'}
        self.assertEqual(self.call('/api/jobs', body, headers={'Origin': 'https://other.example'})[0], 403)
        self.assertEqual(self.call('/.env')[0], 404)
        self.assertEqual(self.call('/api/music/not-a-uuid/audio')[0], 422)
        self.assertEqual(FakeAudio.calls, [])

    def test_prompt_provider_sends_real_image_and_handles_incomplete_json(self):
        artwork = self.artwork()
        answer = {'visual_reading': 'Geometry', 'context_reading': 'Interpretation', 'mapping': ['Grid to rhythm'], 'music_prompt': 'Piano in C'}
        response = Mock(status_code=200)
        response.json.return_value = {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(answer)}}]}
        with patch.object(providers, 'settings', return_value={'DEEPSEEK_API_KEY': 'secret-for-test'}), patch.object(providers.requests, 'post', return_value=response) as post:
            result = providers.artwork_prompt(artwork, platform.DATA/artwork['image'], 16)
            self.assertEqual(result['music_prompt'], 'Piano in C')
            content = post.call_args.kwargs['json']['messages'][1]['content']
            self.assertTrue(content[1]['image_url']['url'].startswith('data:image/jpeg;base64,'))
            response.json.return_value = {'choices': [{'finish_reason': 'length', 'message': {'content': '{}'}}]}
            with self.assertRaises(providers.ProviderError):
                providers.artwork_prompt(artwork, platform.DATA/artwork['image'], 16)

    def test_default_middle_uses_mask_and_rejects_reference_ends_before_paid_requests(self):
        a, b, _, _ = self.saved_pair()
        bridge = self.task('bridge', a_id=a['id'], b_id=b['id'], context=8, bridge=12)
        count = len(FakeAudio.calls)
        invalid = {'request_id': str(uuid.uuid4()), 'kind': 'grid', 'source_job_id': bridge['id'], 'start': 0, 'end': 28}
        self.assertEqual(self.call('/api/jobs', invalid)[0], 422)
        self.assertEqual(len(FakeAudio.calls), count)
        job = self.task('grid', source_job_id=bridge['id'])
        self.assertEqual(job['status'], 'completed', job.get('error'))
        grid = self.json('/api/grids/'+job['result']['grid_id'])
        self.assertEqual(grid['middle_interval'], [8, 20])

    def test_only_one_task_runs_and_stability_request_polls_without_resubmitting(self):
        with patch.object(platform.EXECUTOR, 'submit') as submit:
            artwork = self.artwork()
            body = {'request_id': str(uuid.uuid4()), 'kind': 'music', 'artwork_id': artwork['id'], 'prompt': 'Piano'}
            self.json('/api/jobs', body)
            self.json('/api/jobs', body)
            other = {**body, 'request_id': str(uuid.uuid4())}
            self.assertEqual(self.call('/api/jobs', other)[0], 409)
            self.assertEqual(submit.call_count, 1)
        # Use the real request implementation, not the high-level FakeAudio.
        real_class = self.real_audio_class
        response = Mock(status_code=202)
        response.json.return_value = {'id': 'remote-id'}
        finished = Mock(status_code=200, content=b'RIFF-test-audio')
        events = []
        with patch.object(providers, 'settings', return_value={'STABILITY_API_KEY': 'test-secret'}), \
             patch.object(providers.requests, 'post', return_value=response) as post, \
             patch.object(providers.requests, 'get', side_effect=[Mock(status_code=202), finished]) as get, \
             patch.object(providers.time, 'sleep'):
            client = real_class(events.append)
            output = platform.DATA/'jobs'/'request-test.wav'
            client.generate('Piano', output, 16)
            self.assertEqual(output.read_bytes(), b'RIFF-test-audio')
            self.assertEqual(post.call_count, 1)
            self.assertEqual(get.call_count, 2)
            self.assertEqual(post.call_args.kwargs['data']['output_format'], 'wav')
            self.assertIn('remote:remote-id', events)

    def test_mp3_exports_use_artwork_titles_are_complete_and_do_not_overwrite(self):
        a, b, _, _ = self.saved_pair()
        first = self.task('grid', a_id=a['id'], b_id=b['id'], context=8, bridge=4, name='A custom gallery label')
        self.assertEqual(first['status'], 'completed', first.get('error'))
        grid = self.json('/api/grids/'+first['result']['grid_id'])
        folder = Path(grid['mp3_export']['directory'])
        self.assertTrue(folder.name.startswith('Test Painting - Test Painting'))
        self.assertNotIn('custom gallery', folder.name)
        for index in range(5):
            self.assertEqual(sf.info(folder/f'cell_{index}.mp3').format, 'MP3')
        before = (folder/'cell_2.mp3').read_bytes()
        self.assertEqual(platform.export_grid_mp3(grid)['directory'], str(folder))
        second = self.task('grid', a_id=a['id'], b_id=b['id'], context=8, bridge=4)
        self.assertEqual(second['status'], 'completed', second.get('error'))
        next_grid = self.json('/api/grids/'+second['result']['grid_id'])
        self.assertNotEqual(next_grid['mp3_export']['directory'], str(folder))
        self.assertEqual((folder/'cell_2.mp3').read_bytes(), before)
        self.assertEqual(json.loads((folder/'manifest.json').read_text())['grid_id'], grid['id'])

    def test_named_library_recordings_survive_reopening_the_store(self):
        a, b, _, _ = self.saved_pair()
        with platform.connect() as db:
            count = db.execute("SELECT COUNT(*) FROM records WHERE kind='music'").fetchone()[0]
        self.assertEqual(count, 2)
        self.assertEqual(platform.find('music', a['id'])['name'], 'Painting A')
        self.assertEqual(platform.find('music', b['id'])['name'], 'Painting B')


if __name__ == '__main__':
    unittest.main()
