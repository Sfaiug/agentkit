"""The notes a key's programs send it, read as they are sent.

A unix datagram socket holds `net.unix.max_dgram_qlen` unread notes: 512 on a host, 10 in the
landing's offline sandbox.  A blocking `sendto` past them waits for a reader, so a key that read
its socket only once `ak run` ended would wait on its own socket for ever.  `Notes()` binds a free
abstract address, `address`, and reads it from that moment; `since()` hands back, as text and in
the order sent, the notes since it last asked, every one whose `sendto` has returned.
"""

import select
import socket
import threading


class Notes:
    def __init__(self):
        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self._socket.bind("")   # Linux picks a free abstract name
        self._socket.setblocking(False)
        self.address = self._socket.getsockname()
        self._read, self._lock = [], threading.Lock()
        threading.Thread(target=self._reader, daemon=True).start()

    def since(self):
        with self._lock:
            self._drain()
            read, self._read = self._read, []
        return read

    def _reader(self):
        while True:
            select.select([self._socket], [], [])
            with self._lock:
                self._drain()

    def _drain(self):
        while True:
            try:
                self._read.append(self._socket.recv(1 << 16).decode())
            except BlockingIOError:
                return
