"""Bytes a terminal holds for its reader and nobody has read yet (FIONREAD)."""
import fcntl
import struct
import termios


def unread(fd):
    return struct.unpack("i", fcntl.ioctl(fd, termios.FIONREAD, struct.pack("i", 0)))[0]
