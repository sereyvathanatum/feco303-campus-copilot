"""Fakes for external HTTP services: tests never touch the network."""

import copy


class FakeResponse:
    def __init__(self, status: int, payload=None, text: str = ""):
        self.status_code = status
        self._payload = payload
        self.text = text or (str(payload) if payload is not None else "")
        self.headers = {"content-type": "application/json"}

    def json(self):
        return self._payload


class RecordingSession:
    """A fake `requests.Session`: records every request body and replays queued responses."""

    def __init__(self, responses=None, default=None):
        self.requests: list[dict] = []
        self.responses = list(responses or [])
        self.default = default

    def post(self, url, json=None, timeout=None, headers=None, **kwargs):
        self.requests.append({"url": url, "json": copy.deepcopy(json), "headers": headers or {}, "params": kwargs.get("params")})
        item = self.responses.pop(0) if self.responses else self.default
        if isinstance(item, Exception):
            raise item
        if callable(item):
            return item(url, json)
        return item

    get = post
