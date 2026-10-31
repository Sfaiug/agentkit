//go:build unix

// Package relay runs a program on a terminal of its own and stays its parent, as Python's
// tools/idle-compact.py runs a seat's harness with agentkit/pty_relay.py: what the program prints
// reaches this process's stdout and what is typed on its stdin reaches the program, unchanged.
// Run is all there is to it; the pty, the outer terminal's raw mode and size, the signals passed
// on and the bounded queue each way stay inside.
package relay

import (
	"errors"
	"io"
	"os"
	"os/exec"
	"os/signal"
	"syscall"
	"time"
	"unsafe"
)

// forwarded are the signals the program gets in this process's place, and decides on itself.
var forwarded = []os.Signal{syscall.SIGTERM, syscall.SIGHUP, syscall.SIGINT, syscall.SIGQUIT}

// grace is how long a program the relay ends has between its HUP and its KILL.
const grace = time.Second

// Run runs cmd on a pty of its own as its controlling terminal, once name has taken that
// terminal's path, and relays until cmd exits.  Its terminal has the outer one's size, at the
// start and at each resize; the outer one, where stdin is a terminal, is raw meanwhile.  The
// forwarded signals go on to cmd.  At the end of stdin cmd reads a ^D, and nothing else follows
// from it.  Once cmd exits, what was read and what its terminal holds then is written out,
// however slowly stdout takes it, never waiting for that terminal's end, which a process cmd
// started may hold.  A write to stdout that fails, or a read of stdin that fails short of its
// end, ends the relay, and cmd with it where it still runs: a HUP, then a KILL where it outlives
// grace.  Run answers cmd's exit code, 128+N where signal N ended it; and with why, 127 where
// name fails and 126 where cmd cannot start, as a shell answers, and 1 where the relay fails.
func Run(cmd *exec.Cmd, name func(path string) error) (int, error) {
	master, slave, err := open()
	if err != nil {
		return 126, err
	}
	defer master.Close()
	defer slave.Close()
	// the read end of a pipe whose write end closes once cmd exits: from then on its terminal is
	// read only while it holds something
	drained, drain, err := os.Pipe()
	if err != nil {
		return 126, err
	}
	defer drained.Close()
	defer drain.Close()
	if err := name(slave.Name()); err != nil {
		return 127, err
	}
	var outer *os.File // the first of them that is a terminal
	for _, file := range []*os.File{os.Stdin, os.Stdout, os.Stderr} {
		if _, err := attributes(file); err == nil {
			outer = file
			break
		}
	}
	resize(outer, master)
	signals := make(chan os.Signal, 8)
	signal.Notify(signals, append(forwarded, syscall.SIGWINCH)...)
	defer signal.Stop(signals)
	// caught, so a write to a closed pipe on stdout fails as any write does, instead of Go
	// ending this process with the program still running
	broken := make(chan os.Signal, 1)
	signal.Notify(broken, syscall.SIGPIPE)
	defer signal.Stop(broken)
	if saved, err := attributes(os.Stdin); err == nil {
		raw := saved
		raw.Iflag &^= syscall.BRKINT | syscall.ICRNL | syscall.INPCK | syscall.ISTRIP | syscall.IXON
		raw.Oflag &^= syscall.OPOST
		raw.Cflag = raw.Cflag&^(syscall.CSIZE|syscall.PARENB) | syscall.CS8
		raw.Lflag &^= syscall.ECHO | syscall.ICANON | syscall.IEXTEN | syscall.ISIG
		raw.Cc[syscall.VMIN], raw.Cc[syscall.VTIME] = 1, 0
		if ioctl(os.Stdin, set, unsafe.Pointer(&raw)) == nil {
			defer ioctl(os.Stdin, set, unsafe.Pointer(&saved))
		}
	}
	cmd.Stdin, cmd.Stdout, cmd.Stderr = slave, slave, slave
	cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true, Setctty: true}
	if err := cmd.Start(); err != nil {
		return 126, err
	}
	slave.Close() // only cmd and what it starts hold its terminal: their end is that terminal's
	exited := make(chan struct{})
	go func() {
		cmd.Wait()
		close(exited)
	}()
	in, out := newQueue(), newQueue()
	typed, written := make(chan error, 1), make(chan error, 1)
	go func() {
		switch err := in.fill(os.Stdin.Read); {
		case err == io.EOF || errors.Is(err, syscall.EIO): // EIO is a terminal's end
			in.put([]byte{4})
		case err != nil:
			typed <- err
		}
	}()
	go in.empty(master) // a terminal that takes no more input fails nothing
	go func() {
		from, until := int(master.Fd()), int(drained.Fd()) // numbers, as Fd has none once closed
		out.fill(func(data []byte) (int, error) {
			if err := readable(from, until); err != nil {
				return 0, err
			}
			return master.Read(data)
		})
		out.end()
	}()
	go func() { written <- out.empty(os.Stdout) }()
	for {
		select {
		case got := <-signals:
			if got == syscall.SIGWINCH {
				resize(outer, master)
			} else {
				cmd.Process.Signal(got)
			}
		case err := <-typed:
			return 1, ended(cmd, exited, err)
		case err := <-written:
			if err != nil {
				return 1, ended(cmd, exited, err)
			}
			written = nil // its terminal's end is written out: only cmd's exit is left
		case <-exited:
			drain.Close()
			if written != nil {
				if err := <-written; err != nil {
					return 1, err
				}
			}
			if status, ok := cmd.ProcessState.Sys().(syscall.WaitStatus); ok && status.Signaled() {
				return 128 + int(status.Signal()), nil
			}
			return cmd.ProcessState.ExitCode(), nil
		}
	}
}

// ended ends a cmd still running, as a relay that fails does, and answers why it failed.
func ended(cmd *exec.Cmd, exited <-chan struct{}, why error) error {
	cmd.Process.Signal(syscall.SIGHUP)
	select {
	case <-exited:
	case <-time.After(grace):
		cmd.Process.Kill()
		<-exited
	}
	return why
}

// open is a new pty's two ends, the program's under the path it goes by.
func open() (*os.File, *os.File, error) {
	fd, err := syscall.Open("/dev/ptmx", syscall.O_RDWR|syscall.O_NOCTTY|syscall.O_CLOEXEC, 0)
	if err != nil {
		return nil, nil, err
	}
	master := os.NewFile(uintptr(fd), "/dev/ptmx")
	path, err := unlock(master)
	if err == nil {
		fd, err = syscall.Open(path, syscall.O_RDWR|syscall.O_NOCTTY|syscall.O_CLOEXEC, 0)
	}
	if err != nil {
		master.Close()
		return nil, nil, err
	}
	return master, os.NewFile(uintptr(fd), path), nil
}

// resize gives the pty the outer terminal's size, where there is one.
func resize(outer, master *os.File) {
	var size [4]uint16
	if outer != nil && ioctl(outer, syscall.TIOCGWINSZ, unsafe.Pointer(&size)) == nil {
		ioctl(master, syscall.TIOCSWINSZ, unsafe.Pointer(&size))
	}
}

// attributes are a terminal's modes; an error where file is no terminal.
func attributes(file *os.File) (syscall.Termios, error) {
	var modes syscall.Termios
	return modes, ioctl(file, get, unsafe.Pointer(&modes))
}

func ioctl(file *os.File, request uintptr, arg unsafe.Pointer) error {
	if _, _, errno := syscall.Syscall(syscall.SYS_IOCTL, file.Fd(), request, uintptr(arg)); errno != 0 {
		return errno
	}
	return nil
}

// readable waits until master has something to read, or answers io.EOF once drained is readable
// while master is not.
func readable(master, drained int) error {
	for {
		var ready syscall.FdSet
		mark(ready.Bits[:], master)
		mark(ready.Bits[:], drained)
		err := wait(max(master, drained)+1, &ready)
		switch {
		case err == syscall.EINTR:
		case err != nil:
			return err
		case marked(ready.Bits[:], master):
			return nil
		default:
			return io.EOF
		}
	}
}

// mark puts fd in an fd_set's bits, whatever the width of their words.
func mark[Word int32 | int64](bits []Word, fd int) {
	width := int(unsafe.Sizeof(bits[0])) * 8
	bits[fd/width] |= 1 << (fd % width)
}

func marked[Word int32 | int64](bits []Word, fd int) bool {
	width := int(unsafe.Sizeof(bits[0])) * 8
	return bits[fd/width]&(1<<(fd%width)) != 0
}
