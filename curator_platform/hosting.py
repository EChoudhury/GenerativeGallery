"""Deployment settings. Local defaults, password protection, or explicitly enabled public access."""
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
import base64
import binascii
import hmac
import os


@dataclass(frozen=True)
class Hosting:
    public_url: str
    username: str
    password: str
    allowed_hosts: tuple[str, ...]
    data: Path
    exports: Path

    @classmethod
    def from_env(cls, root, environ=None):
        env = os.environ if environ is None else environ
        url = (env.get('CURATOR_PUBLIC_URL') or env.get('RENDER_EXTERNAL_URL') or '').rstrip('/')
        username = env.get('CURATOR_USERNAME', 'curator')
        password = env.get('CURATOR_PASSWORD', '')
        hosts = ['localhost', '127.0.0.1', 'testserver']
        if url:
            parsed = urlsplit(url)
            if parsed.scheme != 'https' or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
                raise ValueError('CURATOR_PUBLIC_URL must be an HTTPS origin, such as https://gallery.onrender.com.')
            if len(password) < 16 and env.get('CURATOR_PUBLIC_GENERATION') != 'true':
                raise ValueError('Set CURATOR_PASSWORD to at least 16 characters, or explicitly set CURATOR_PUBLIC_GENERATION=true for open access.')
            hosts.append(parsed.hostname)
        if not username or ':' in username:
            raise ValueError('CURATOR_USERNAME must be nonempty and cannot contain a colon.')
        return cls(url, username, password, tuple(hosts),
                   Path(env.get('CURATOR_DATA_DIR') or root/'data').expanduser().resolve(),
                   Path(env.get('CURATOR_EXPORT_DIR') or root.parent/'audio').expanduser().resolve())

    def authorized(self, header):
        if not self.password:
            return True
        try:
            scheme, value = header.split(' ', 1)
            if scheme.lower() != 'basic':
                return False
            raw = base64.b64decode(value, validate=True)
            username, password = raw.split(b':', 1)
            user_ok = hmac.compare_digest(username, self.username.encode('utf-8'))
            password_ok = hmac.compare_digest(password, self.password.encode('utf-8'))
            return user_ok and password_ok
        except (ValueError, binascii.Error):
            return False
