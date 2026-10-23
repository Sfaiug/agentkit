"""The answer key's webhook keeps every request whole and answers as the test scripted.

Every key test of a page reads it from tests/fixtures/sink.py, and every test of a refused,
throttled or failing webhook gets its refusal there; both hold only if the sink does.
"""

import http.client
import json
import sys
from pathlib import Path
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures.akbin import Home
from fixtures.sink import Sink

POST = """import json, os, urllib.request
ask = urllib.request.Request(os.environ["AK_NOTIFY_SINK"] + "&wait=true", method="POST",
                             data=json.dumps({"content": "hi"}).encode(),
                             headers={"Content-Type": "application/json", "X-Acme": "beta"})
print(urllib.request.urlopen(ask, timeout=30).read().decode())
"""


# The test's own environment may name a proxy, and loopback must not go through it.
DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def ask(url, data=None, method="POST"):
    """(status, headers, body) of one request; a refusal is an answer too."""
    try:
        with DIRECT.open(urllib.request.Request(url, data=data, method=method),
                         timeout=30) as reply:
            return reply.status, reply.headers, reply.read()
    except urllib.error.HTTPError as refused:
        return refused.code, refused.headers, refused.read()


class Sinks(unittest.TestCase):
    def setUp(self):
        self.home = Home()
        self.addCleanup(self.home.close)
        self.sink = Sink(self.home, "/hook?thread_id=7")
        self.addCleanup(self.sink.close)

    def test_a_program_in_the_home_reaches_it_and_its_request_is_kept_whole(self):
        done = self.home.run(sys.executable, "-c", POST)
        self.assertEqual((done.code, json.loads(done.out)), (0, {"id": "1001"}), done.err)
        request, = self.sink.requests
        self.assertEqual((request.method, request.path, request.query),
                         ("POST", "/hook", {"thread_id": "7", "wait": "true"}))
        self.assertEqual(request.headers["x-acme"], "beta")
        self.assertEqual(request.headers["content-type"], "application/json")
        self.assertEqual((request.body, request.json), (b'{"content": "hi"}', {"content": "hi"}))
        self.assertEqual(self.sink.pages(), ["hi"])

    def test_scripted_replies_answer_in_order_and_then_a_message_id(self):
        self.sink.script(404, (429, {"Retry-After": "120"}, {"retry_after": 120}),
                         (503, None, "down"))
        replies = [ask(self.sink.url, b"{}") for _ in range(4)]
        self.assertEqual([(status, body) for status, _, body in replies],
                         [(404, b""), (429, b'{"retry_after": 120}'), (503, b"down"),
                          (200, b'{"id": "1004"}')])
        self.assertEqual(replies[1][1]["Retry-After"], "120")
        self.assertEqual(replies[1][1]["Content-Type"], "application/json")

    def test_a_body_that_is_not_json_or_comes_in_chunks_is_kept(self):
        ask(self.sink.url, b"plain words")
        self.assertEqual(ask(self.sink.url, method="GET")[0], 200)
        port = int(self.sink.url.split(":")[2].split("/")[0])
        chunked = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
        chunked.request("POST", "/hook", body=iter([b'{"content": ', b'"in parts"}']),
                        encode_chunked=True)
        self.assertEqual(chunked.getresponse().status, 200)
        chunked.close()
        plain, got, parts = self.sink.wait(3)
        self.assertEqual((plain.body, plain.json), (b"plain words", None))
        self.assertEqual((got.method, got.body), ("GET", b""))
        self.assertEqual(parts.json, {"content": "in parts"})

    def test_closing_gives_the_home_its_sink_back_and_a_wait_names_what_came(self):
        ask(self.sink.url, b"{}")
        with self.assertRaisesRegex(AssertionError, "took .*POST.*not 2 requests"):
            self.sink.wait(2, bound=0.2)
        self.assertEqual(self.home.env["AK_NOTIFY_SINK"], self.sink.url)
        self.sink.close()
        self.assertEqual(self.home.env["AK_NOTIFY_SINK"], "dry-run")


if __name__ == "__main__":
    unittest.main()
