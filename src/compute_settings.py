"""Private, revisioned target configuration. Reading never creates a store."""
from contextlib import contextmanager
from dataclasses import dataclass, field
import fcntl
import json
import os
from pathlib import Path
import tempfile
import threading
from urllib.parse import urlsplit

DEFAULT_URL = 'http://127.0.0.1:8189'
CONFIG_LOCK = threading.RLock()


class SettingsError(ValueError):
    def __init__(self, message, status=422):
        super().__init__(message)
        self.status = status


def validated_url(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 2048:
        raise SettingsError('Enter an API v2 http(s) URL.')
    value = value.strip().rstrip('/')
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        raise SettingsError('Enter a valid API v2 URL.') from None
    if (parts.scheme not in {'http', 'https'} or not parts.hostname or
            parts.username or parts.password or parts.query or parts.fragment or
            any(ord(c) < 33 for c in value)):
        raise SettingsError('Use an http(s) URL without credentials, query or fragment.')
    return value


def target_mode(url):
    host = urlsplit(url).hostname.lower()
    if host in {'127.0.0.1', 'localhost', '::1'}:
        return 'self-hosted'
    if host == 'cloud.comfy.org':
        return 'comfy-cloud'
    if host.endswith('.run.comfy.app'):
        return 'comfy-api-deployment'
    return 'remote-self-hosted'


@dataclass(frozen=True)
class Target:
    base_url: str
    api_key: str = field(default='', repr=False)
    revision: int = 0
    source: str = 'default'

    def public(self):
        return {'revision': self.revision, 'base_url': self.base_url,
                'api_key_configured': bool(self.api_key), 'source': self.source,
                'mode': target_mode(self.base_url)}


class Store:
    def __init__(self, work):
        self.path = Path(work)/'settings'/'compute.json'

    def current(self):
        if self.path.is_symlink():
            raise SettingsError('Compute settings storage must not be a symbolic link.', 503)
        if not self.path.exists():
            explicit = os.environ.get('OPENGENJUTSU_COMFY_BASE_URL', '').strip()
            return Target(validated_url(explicit or DEFAULT_URL),
                          os.environ.get('COMFY_API_KEY', '').strip(), source='environment' if explicit else 'default')
        try:
            if self.path.stat().st_size > 16384:
                raise ValueError()
            data = json.loads(self.path.read_text())
            if (set(data) != {'revision', 'base_url', 'api_key'} or
                    type(data['revision']) is not int or data['revision'] < 1):
                raise ValueError()
            key = self._key(data['api_key'])
            return Target(validated_url(data['base_url']), key, data['revision'], 'saved')
        except (OSError, ValueError, TypeError, KeyError):
            raise SettingsError('Saved compute settings are unreadable; no fallback target was selected.', 503) from None

    @staticmethod
    def _key(value):
        if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 32 or ord(c) > 126 for c in value):
            raise SettingsError('Invalid API key format.')
        return value.strip()

    def candidate(self, base_url, api_key=None, clear=False):
        base = validated_url(base_url)
        if type(clear) is not bool:
            raise SettingsError('Invalid credential removal flag.')
        current = self.current()
        key = self._key(api_key) if api_key is not None else ''
        if clear and key:
            raise SettingsError('Choose either a new API key or credential removal.')
        if not key and not clear and base == current.base_url:
            key = current.api_key
        return Target(base, '' if clear else key, current.revision, 'saved')

    def save(self, revision, base_url, api_key=None, clear=False):
        with CONFIG_LOCK:
            return self._save(revision, base_url, api_key, clear)

    def _save(self, revision, base_url, api_key=None, clear=False):
        if type(revision) is not int or revision < 0:
            raise SettingsError('A valid settings revision is required.')
        folder = self.path.parent
        if folder.is_symlink():
            raise SettingsError('Compute settings storage must not be a symbolic link.', 503)
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(folder, 0o700)
        fd = os.open(folder/'compute.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'a') as lock:
            os.fchmod(lock.fileno(), 0o600)
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise SettingsError('Settings are being saved elsewhere. Retry after reload.', 409) from None
            current = self.current()
            if current.revision != revision:
                raise SettingsError('Settings changed elsewhere. Reload before saving.', 409)
            chosen = self.candidate(base_url, api_key, clear)
            record = {'revision': revision+1, 'base_url': chosen.base_url, 'api_key': chosen.api_key}
            fd, name = tempfile.mkstemp(prefix='.compute-', dir=folder)
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as output:
                    json.dump(record, output, ensure_ascii=False); output.flush(); os.fsync(output.fileno())
                os.replace(name, self.path)
                directory = os.open(folder, os.O_RDONLY)
                try: os.fsync(directory)
                finally: os.close(directory)
            finally:
                Path(name).unlink(missing_ok=True)
        return Target(chosen.base_url, chosen.api_key, revision+1, 'saved')


@contextmanager
def sdk_environment(target):
    """SDK0.5 reads env at construction. Serialize, then restore ambient values."""
    with CONFIG_LOCK:
        previous = {key: os.environ.get(key) for key in ('COMFY_BASE_URL', 'COMFY_API_KEY')}
        os.environ['COMFY_BASE_URL'] = target.base_url
        if target.api_key:
            os.environ['COMFY_API_KEY'] = target.api_key
        else:
            os.environ.pop('COMFY_API_KEY', None)
        try:
            yield
        finally:
            for key, value in previous.items():
                if value is None: os.environ.pop(key, None)
                else: os.environ[key] = value
