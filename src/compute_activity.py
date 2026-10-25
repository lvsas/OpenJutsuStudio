"""Prevent target activation from crossing a submission/worker boundary."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import threading
from compute_settings import SettingsError


class Activity:
    def __init__(self, extra_busy=lambda: False):
        self.lock = threading.RLock()
        self.count = 0
        self.extra_busy = extra_busy

    def acquire(self):
        with self.lock:
            self.count += 1
        released = False
        def release(*_):
            nonlocal released
            with self.lock:
                if not released:
                    released = True
                    self.count -= 1
        return release

    @contextmanager
    def guard(self):
        with self.lock:
            if self.count or self.extra_busy():
                raise SettingsError('Work is in progress. Wait before changing the compute target.', 409)
            yield


class LeasedExecutor(ThreadPoolExecutor):
    def __init__(self, *args, activity, **kwargs):
        super().__init__(*args, **kwargs)
        self.activity = activity

    def submit(self, fn, /, *args, **kwargs):
        release = self.activity.acquire()
        try:
            future = super().submit(fn, *args, **kwargs)
        except BaseException:
            release(); raise
        future.add_done_callback(release)
        return future


class ActivityMiddleware:
    """Pure ASGI: keep the lease through streaming and background responses."""
    def __init__(self, app, activity):
        self.app, self.activity = app, activity

    async def __call__(self, scope, receive, send):
        mutating = (scope['type'] == 'http' and scope.get('method') in {'POST', 'PUT', 'PATCH', 'DELETE'}
                    and not scope.get('path', '').startswith('/api/settings/'))
        release = self.activity.acquire() if mutating else lambda: None
        try:
            await self.app(scope, receive, send)
        finally:
            release()
