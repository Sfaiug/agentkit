"""The owner's notification webhook, stood in for by a loopback HTTP server of the test's own.

`Sink(home)` listens on 127.0.0.1 and points the Home's `AK_NOTIFY_SINK` at itself, the variable
that outranks any webhook a config or secret names, so every page the program sends lands here
and none can reach a person.  It keeps each request it is sent, oldest first, as a `Request`:
its method, its path and its query apart, its headers by lowercased name (HTTP's names have no
case, and each client spells them its own way), its body, and that body read as JSON (None when
it is not).  It answers as `script` says, in order, and after that with 200 and a message id, as
a webhook does: `{"id": "1001"}` for the first request it takes.  A scripted reply is a status,
or (status, headers, body) with a JSON or text body, so a refusal, an outage or a rate limit
with its wait is one line:

    from fixtures.akbin import Home
    from fixtures.akseat import Seat
    from fixtures.sink import Sink
    with Home() as home, Sink(home) as sink:
        sink.script((429, {"Retry-After": "120"}, {"retry_after": 120}))
        Seat(home, "acme")
        home.ak("notify", "needs", "Which branch?", "--session", "acme")
        refused, = sink.wait(1)
        assert refused.query["wait"] == "true"
        assert sink.pages() == ["🙋 Needs you · acme"]

`url` is where it listens: `path` may carry a query, `Sink(home, "/hook?thread_id=7")`.
`close`, or leaving `with`, stops it and gives the Home back the sink it had.
"""

from collections import namedtuple
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import time
from urllib.parse import parse_qsl, urlsplit

Request = namedtuple("Request", "method path query headers body json")


class Sink:
    def __init__(self, home, path="/hook"):
        self.home, self._was = home, home.env.get("AK_NOTIFY_SINK")
        self._requests, self._replies, self._lock = [], [], threading.Lock()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(self))
        self.port = self._server.server_port
        self.url = f"http://127.0.0.1:{self.port}{path}"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        home.env["AK_NOTIFY_SINK"] = self.url

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()

    def close(self):
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        self._server = None
        if self._was is None:
            self.home.env.pop("AK_NOTIFY_SINK", None)
        else:
            self.home.env["AK_NOTIFY_SINK"] = self._was

    def script(self, *replies):
        """Answer the next requests so, in order, before the default 200."""
        with self._lock:
            self._replies.extend(replies)

    @property
    def requests(self):
        """Every request taken so far, oldest first."""
        with self._lock:
            return list(self._requests)

    def pages(self):
        """What each page said: the `content` of every POST, oldest first."""
        return [(request.json or {}).get("content") for request in self.requests
                if request.method == "POST"]

    def wait(self, count, bound=30):
        """The requests once there are `count` of them: a page sent from the background comes
        when it is sent, and a test that reads earlier reads nothing."""
        deadline = time.monotonic() + bound
        while len(self.requests) < count:
            if time.monotonic() > deadline:
                raise AssertionError(f"the sink took {self.requests}, not {count} requests")
            time.sleep(0.05)
        return self.requests

    def _take(self, handler):
        """Keep one request and choose its answer, under the lock: requests may come at once."""
        body = _body(handler)
        try:
            parsed = json.loads(body) if body else None
        except ValueError:
            parsed = None
        parts = urlsplit(handler.path)
        request = Request(handler.command, parts.path, dict(parse_qsl(parts.query)),
                          {name.lower(): value for name, value in handler.headers.items()},
                          body, parsed)
        with self._lock:
            self._requests.append(request)
            reply = (self._replies.pop(0) if self._replies else
                     (200, None, {"id": str(1000 + len(self._requests))}))
        status, headers, answer = (*((reply,) if isinstance(reply, int) else reply),
                                   None, None)[:3]
        return status, headers or {}, answer


def _body(handler):
    """The request's body, whether its client gave its length or sent it in chunks."""
    if handler.headers.get("Transfer-Encoding", "").lower() != "chunked":
        return handler.rfile.read(int(handler.headers.get("Content-Length") or 0))
    body = b""
    while size := int(handler.rfile.readline().split(b";")[0], 16):
        body += handler.rfile.read(size)
        handler.rfile.readline()
    while handler.rfile.readline().strip():
        pass        # the trailer, up to its blank line
    return body


def _handler(sink):
    class Handler(BaseHTTPRequestHandler):
        def answer(self):
            status, headers, body = sink._take(self)
            data = (b"" if body is None else body.encode() if isinstance(body, str) else
                    json.dumps(body).encode())
            self.send_response(status)
            if body is not None and not any(name.lower() == "content-type" for name in headers):
                self.send_header("Content-Type", "text/plain" if isinstance(body, str) else
                                 "application/json")
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_POST = do_PATCH = do_PUT = do_DELETE = answer

        def log_message(self, *_args):
            pass    # the test's output is its own

    return Handler
