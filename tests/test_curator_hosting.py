import base64
from pathlib import Path
import unittest
from curator_platform.hosting import Hosting


class HostingTests(unittest.TestCase):
    def test_local_and_explicit_public_access(self):
        root = Path('/tmp/project/curator_platform')
        local = Hosting.from_env(root, {})
        self.assertEqual(local.data, (root/'data').resolve())
        self.assertTrue(local.authorized(''))
        with self.assertRaises(ValueError):
            Hosting.from_env(root, {'CURATOR_PUBLIC_URL': 'https://gallery.example'})
        public = Hosting.from_env(root, {'CURATOR_PUBLIC_URL': 'https://gallery.example',
                                        'CURATOR_PUBLIC_GENERATION': 'true',
                                        'CURATOR_DATA_DIR': '/tmp/gallery-data',
                                        'CURATOR_EXPORT_DIR': '/tmp/gallery-audio'})
        self.assertIn('gallery.example', public.allowed_hosts)
        self.assertEqual(public.data, Path('/tmp/gallery-data').resolve())
        self.assertEqual(public.exports, Path('/tmp/gallery-audio').resolve())
        self.assertTrue(public.authorized(''))

    def test_https_and_password(self):
        root = Path('/tmp/project/curator_platform')
        for url in ['http://gallery.example', 'https://gallery.example/path', 'https://user:pass@gallery.example']:
            with self.assertRaises(ValueError):
                Hosting.from_env(root, {'CURATOR_PUBLIC_URL': url, 'CURATOR_PUBLIC_GENERATION': 'true'})
        password = 'a-long-unicode-password-画作'
        hosted = Hosting.from_env(root, {'RENDER_EXTERNAL_URL': 'https://gallery.onrender.com',
                                         'CURATOR_PASSWORD': password})
        auth = 'Basic '+base64.b64encode(('curator:'+password).encode()).decode()
        self.assertTrue(hosted.authorized(auth))
        for bad in ['', 'Bearer token', 'Basic !!!', 'Basic YQ==', 'Basic dXNlcjpwYXNz']:
            self.assertFalse(hosted.authorized(bad))
