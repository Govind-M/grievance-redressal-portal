"""Worker-local bounded throttling/cache; contains hashes/results, never draft text."""

from collections import OrderedDict, deque
from threading import Lock
from time import monotonic

from fastapi import Request

from app.integrations.gemini import GeminiProvider
from app.modules.ai.errors import AIQuotaExceeded


class AIRuntime:
    def __init__(self, settings, provider=None):
        self.settings = settings
        self.provider = provider if provider is not None else GeminiProvider(settings)
        self._lock = Lock()
        self._requests = OrderedDict()
        self._cache = OrderedDict()

    def charge(self, user_id):
        with self._lock:
            stamp = monotonic()
            key = str(user_id)
            queue = self._requests.setdefault(key, deque())
            while queue and queue[0] <= stamp - 60:
                queue.popleft()
            if len(queue) >= self.settings.ai_requests_per_minute:
                raise AIQuotaExceeded()
            queue.append(stamp)
            self._requests.move_to_end(key)
            while len(self._requests) > 4096:
                self._requests.popitem(last=False)

    def cached(self, key):
        with self._lock:
            item = self._cache.get(key)
            if item and item[0] > monotonic():
                self._cache.move_to_end(key)
                return item[1].model_copy(deep=True)
            self._cache.pop(key, None)
            return None

    def remember(self, key, result):
        with self._lock:
            self._cache[key] = (
                monotonic() + self.settings.ai_cache_seconds,
                result.model_copy(deep=True),
            )
            while len(self._cache) > 1024:
                self._cache.popitem(last=False)


def get_runtime(request: Request) -> AIRuntime:
    return request.app.state.ai_runtime
