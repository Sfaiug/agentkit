"""Bounded, nonblocking terminal transport, independent of the program in the PTY."""
import errno
import os
import select
import time

# A ceiling on queued bytes per direction, not a throughput limit. A slow reader
# backs up its writer; readiness lets a faster one use the next chunk immediately.
BUFFER_LIMIT = 64 * 1024


class Relay:
    def __init__(self, master, stdin, stdout, output, alive=lambda: True):
        self.master, self.stdin, self.stdout = master, stdin, stdout
        self.output, self.alive = output, alive
        self.input_open = self.master_open = self.writable = True
        self.to_child, self.to_owner = bytearray(), bytearray()
        # stdin and stdout may share an open file description. Save all three
        # before changing any, and restore them before the caller closes them.
        self.blocking = {fd: os.get_blocking(fd) for fd in (master, stdin, stdout)}
        try:
            for fd in self.blocking:
                os.set_blocking(fd, False)
        except BaseException:
            self.close()
            raise

    def close(self):
        for fd, blocking in self.blocking.items():
            os.set_blocking(fd, blocking)

    @property
    def active(self):
        return self.master_open or bool(self.to_owner)

    def caught_up(self, *, output=True):
        """Input has reached the child; optionally require a current screen too.

        A caller with authoritative lifecycle hooks need not wait for repaints,
        but a caller deciding from screen bytes must observe pending output first.
        """
        reads = [self.stdin] if self.input_open else []
        if output:
            reads.append(self.master)
        return (self.master_open and not self.to_child and (not output or not self.to_owner)
                and not select.select(reads, [], [], 0)[0])

    def poll(self, timeout, *, input=True):
        """Move ready bytes in both directions; return whether anything moved.

        No write, including one following writable readiness, may block: a PTY
        can accept only part of it. Full queues stop reads in that direction only.
        """
        reads, writes = [], []
        if self.master_open and len(self.to_owner) < BUFFER_LIMIT:
            reads.append(self.master)
        if input and self.input_open and self.writable and len(self.to_child) < BUFFER_LIMIT:
            reads.append(self.stdin)
        if self.to_owner:
            writes.append(self.stdout)
        if self.to_child and self.writable:
            writes.append(self.master)
        try:
            ready, _, _ = select.select(reads, writes, [], max(0, timeout))
        except InterruptedError:
            return False
        moved = False
        for fd, pending in ((self.master, self.to_owner), (self.stdin, self.to_child)):
            if fd not in ready:
                continue
            try:
                data = os.read(fd, BUFFER_LIMIT - len(pending))
            except (BlockingIOError, InterruptedError):
                continue
            except OSError as exc:
                if exc.errno != errno.EIO:
                    raise
                data = b''
            if data:
                pending.extend(data)
                if fd == self.master:
                    self.output(data)
                moved = True
            elif fd == self.master:
                self.master_open = self.writable = False
                self.to_child.clear()
                moved = True
            else:
                self.input_open = False
                self.to_child.extend(b'\x04')
                moved = True
        # Write new reads in this poll too: leaving a draft only in our queue
        # hides it from terminal unread-input checks until the next poll.
        for fd, pending in ((self.stdout, self.to_owner), (self.master, self.to_child)):
            if fd == self.master and not self.writable:
                continue
            while pending:
                try:
                    count = os.write(fd, pending)
                except BlockingIOError:
                    break
                except InterruptedError:
                    continue
                except OSError as exc:
                    if fd == self.master and exc.errno == errno.EIO:
                        self.writable = False
                        pending.clear()
                        break
                    raise
                if not count:
                    raise OSError(errno.EIO, 'zero-byte terminal write')
                del pending[:count]
                moved = True
        return moved

    def send(self, groups, gap):
        """Type key groups in order while continuing to drain terminal output.

        Owner input waits in its terminal during the sequence, as it does while
        a user types a command. Each gap starts after the preceding keys reached
        the child, not when they were queued behind a slow reader.
        """
        for index, keys in enumerate(groups):
            if index:
                until = time.monotonic() + gap
                while time.monotonic() < until:
                    if not self.alive() or not self.master_open:
                        return False
                    self.poll(until - time.monotonic(), input=False)
            view = memoryview(keys)
            while view or self.to_child:
                if not self.alive() or not self.writable:
                    return False
                count = min(len(view), BUFFER_LIMIT - len(self.to_child))
                self.to_child.extend(view[:count])
                view = view[count:]
                self.poll(gap, input=False)
        return True

    def finish(self):
        """Drain the exited child's available output, including queued bytes.

        A descendant may still hold the slave, so its EOF is not required after
        our own child exits. Only data already available belongs to this drain.
        """
        self.writable = False
        self.to_child.clear()
        while self.to_owner or self.poll(0, input=False):
            if self.to_owner:
                self.poll(0.1, input=False)
