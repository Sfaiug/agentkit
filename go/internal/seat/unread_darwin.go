package seat

// fionread is FIONREAD, _IOR('f', 127, int), which Go's syscall leaves out on darwin.
const fionread = 0x4004667f
