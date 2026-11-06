//go:build linux || darwin

package terminal

import (
	"context"
	"os"
	"os/exec"
	"os/signal"
	"regexp"
	"strconv"
	"sync"
	"sync/atomic"
	"syscall"
	"time"
	"unsafe"
)

// The alternate screen, the cursor hidden and every move of the pointer reported in SGR form; and
// all of it undone in reverse, any synchronized update ended with it.
const (
	takeModes = "\x1b[?1049h\x1b[?25l\x1b[?1003h\x1b[?1006h"
	giveModes = "\x1b[?1006l\x1b[?1003l\x1b[?25h\x1b[?1049l\x1b[?2026l"
	inFD      = 0
	outFD     = 1
)

var (
	backgroundSaid = regexp.MustCompile(`\x1b\]11;([^\x07\x1b]*)(?:\x07|\x1b\\)`)
	attributesSaid = regexp.MustCompile(`\x1b\[\?[0-9;]*c`)
)

// Keyboard hides the terminal: its line discipline and modes (Take, Give), what it is (Sense), the
// signals that must give it back, and the bytes that make a key (ReadKey).  Every signal is answered
// inside ReadKey, on the goroutine that draws, so no frame can land on a screen already given back.
type Keyboard struct {
	saved   syscall.Termios
	taken   bool
	screen  bool
	sensed  Screen
	keyed   []byte // what was read past a key, or typed while Sense waited
	unread  []Key  // keys a wait read and kept for the screen after it (Unread)
	woken   [2]*os.File
	wake    atomic.Bool
	mu      sync.Mutex
	pending []os.Signal
	cont    chan os.Signal
	heard   chan os.Signal
}

// NewKeyboard takes nothing yet, and leaves what ends or stops the program to its defaults till
// Take: a read before that can still be cut short.
func NewKeyboard() *Keyboard {
	k := &Keyboard{cont: make(chan os.Signal, 1)}
	k.woken[0], k.woken[1], _ = os.Pipe()
	signal.Notify(k.cont, syscall.SIGCONT)
	k.heard = make(chan os.Signal, 8)
	go func() {
		for each := range k.heard {
			k.mu.Lock()
			k.pending = append(k.pending, each)
			k.mu.Unlock()
			k.woken[1].Write([]byte{'.'})
		}
	}()
	return k
}

// Take makes keys arrive one at a time, unechoed, on the alternate screen.
func (k *Keyboard) Take() {
	k.take(true)
}

// Give puts the terminal back exactly as Take found it.
func (k *Keyboard) Give() { k.give(giveModes) }

func (k *Keyboard) give(modes string) {
	if !k.taken {
		return
	}
	k.taken = false
	if k.screen {
		syscall.Write(outFD, []byte(modes))
	}
	attrs(setAttrs, &k.saved)
	signal.Stop(k.heard)
}

// Sense asks what the terminal is, once a start, on a taken keyboard: whether it takes true colour
// though COLORTERM does not say (what AGENTKIT_TERMFEATURES says, else inside tmux what tmux says,
// which takes a process), and whether its background is light, by its answer to OSC 11 within a
// tenth of a second.  DA1, which every terminal answers and in turn, ends the wait early.  Anything
// typed meanwhile is kept for ReadKey.
func (k *Keyboard) Sense() {
	features, set := os.LookupEnv("AGENTKIT_TERMFEATURES")
	if !set && os.Getenv("TMUX") != "" { // asked of the client this runs under, $TMUX kept
		asked, cancel := context.WithTimeout(context.Background(), time.Second)
		said, _ := exec.CommandContext(asked, "tmux", "display", "-p", "#{client_termfeatures}").Output()
		cancel()
		features = string(said)
	}
	syscall.Write(outFD, []byte("\x1b]11;?\x1b\\\x1b[c"))
	var heard []byte
	until := time.Now().Add(100 * time.Millisecond)
	for !attributesSaid.Match(heard) {
		each, got := readByte(time.Until(until))
		if !got {
			break
		}
		heard = append(heard, each)
	}
	said := backgroundSaid.FindSubmatchIndex(heard)
	light := false
	if said != nil {
		light = isLight(string(heard[said[2]:said[3]]))
		heard = append(heard[:said[0]:said[0]], heard[said[1]:]...)
	}
	if at := attributesSaid.FindIndex(heard); at != nil {
		heard = append(heard[:at[0]:at[0]], heard[at[1]:]...)
	}
	k.keyed = append(heard, k.keyed...)
	k.sensed = Screen{depth: depth(os.Stdout, trueColour(features)), ascii: !utf8(), light: light}
}

// Screen is what Sense found, at the size the terminal is now.
func (k *Keyboard) Screen() Screen {
	screen := k.sensed
	screen.width, screen.height = width(os.Stdout), height(os.Stdout)
	return screen
}

// Wake ends the wait of a ReadKey with `wake`, from any goroutine.
func (k *Keyboard) Wake() {
	k.wake.Store(true)
	k.woken[1].Write([]byte{'.'})
}

// ReadKey waits for the next key, answering what happens meanwhile.  A kill, a hang-up, ^\ or ^C
// gives the terminal back and exits as a shell reports that signal; a stop gives it back, stops, and
// on going on takes it again; a resize or that return says `again`.
func (k *Keyboard) ReadKey() Key {
	for {
		if k.answer() {
			return Key{Name: "again"}
		}
		if k.wake.Swap(false) {
			return Key{Name: "wake"}
		}
		if len(k.unread) > 0 {
			key := k.unread[0]
			k.unread = k.unread[1:]
			return key
		}
		first, got := k.keyedByte()
		if !got {
			keyboard, woken := wait(int(k.woken[0].Fd()), -1)
			if woken {
				k.woken[0].Read(make([]byte, 64))
			}
			if !keyboard {
				continue
			}
			var gone bool
			if first, gone = readOne(); gone {
				return Key{Name: "eof"}
			}
		}
		key, kept, ok := spell(first, k.next)
		k.keyed = append(kept, k.keyed...)
		if ok && wheel(key) {
			key, ok = k.notches(key)
		}
		if ok {
			return key
		}
	}
}

// answer answers the signal heard first, and whether there was one: what is left is a resize or a
// return from a stop, each asking for a draw.
func (k *Keyboard) answer() bool {
	k.mu.Lock()
	var heard os.Signal
	if len(k.pending) > 0 {
		heard, k.pending = k.pending[0], k.pending[1:]
	}
	k.mu.Unlock()
	switch heard {
	case nil:
		return false
	case syscall.SIGTSTP:
		k.stop()
	case syscall.SIGWINCH:
	default:
		k.Give()
		os.Exit(128 + int(heard.(syscall.Signal)))
	}
	return true
}

// stop hands the terminal over and stops, which only a person's `fg` or a SIGCONT undoes.
func (k *Keyboard) stop() {
	screen := k.screen
	k.Give()
	select {
	case <-k.cont:
	default:
	}
	syscall.Kill(syscall.Getpid(), syscall.SIGSTOP)
	<-k.cont
	k.take(screen)
}

func (k *Keyboard) keyedByte() (byte, bool) {
	if len(k.keyed) == 0 {
		return 0, false
	}
	first := k.keyed[0]
	k.keyed = k.keyed[1:]
	return first, true
}

// next is the byte after the one a key started with.
func (k *Keyboard) next(within time.Duration) (byte, bool) {
	if first, got := k.keyedByte(); got {
		return first, true
	}
	return readByte(within)
}

// readByte is a byte sent within that long, false where none was or the keyboard is gone.
func readByte(within time.Duration) (byte, bool) {
	if ready, _ := wait(-1, max(within, 0)); !ready {
		return 0, false
	}
	first, gone := readOne()
	return first, !gone
}

// readOne reads the byte waiting, and whether the keyboard is gone instead.
func readOne() (byte, bool) {
	var one [1]byte
	for {
		count, err := syscall.Read(inFD, one[:])
		if err == syscall.EINTR {
			continue
		}
		return one[0], err != nil || count == 0
	}
}

// wait is whether the keyboard and the other descriptor (none where negative) have something to
// read, once one does or that long has passed, for ever where it is negative.
func wait(other int, within time.Duration) (keyboard, woken bool) {
	until := time.Now().Add(within)
	for {
		var set syscall.FdSet
		mark(&set, inFD)
		if other >= 0 {
			mark(&set, other)
		}
		var limit *syscall.Timeval
		if within >= 0 {
			left := syscall.NsecToTimeval(max(int64(time.Until(until)), 0))
			limit = &left
		}
		if err := selected(max(inFD, other)+1, &set, limit); err == syscall.EINTR {
			continue
		} else if err != nil {
			return true, false // a read then says what became of it
		}
		return marked(&set, inFD), other >= 0 && marked(&set, other)
	}
}

// mark and marked reach a descriptor's bit whatever word size this system's FdSet has.
func mark(set *syscall.FdSet, fd int) {
	unsafe.Slice((*byte)(unsafe.Pointer(set)), unsafe.Sizeof(*set))[fd/8] |= 1 << (fd % 8)
}

func marked(set *syscall.FdSet, fd int) bool {
	return unsafe.Slice((*byte)(unsafe.Pointer(set)), unsafe.Sizeof(*set))[fd/8]&(1<<(fd%8)) != 0
}

// attrs reads or sets the terminal's attributes, a set waiting for what was written to go out.
func attrs(request uintptr, state *syscall.Termios) error {
	if _, _, errno := syscall.Syscall(syscall.SYS_IOCTL, inFD, request, uintptr(unsafe.Pointer(state))); errno != 0 {
		return errno
	}
	return nil
}

// height is LINES where it is a positive number, else the terminal's, else 24.
func height(file *os.File) int {
	if lines, err := strconv.Atoi(os.Getenv("LINES")); err == nil && lines > 0 {
		return lines
	}
	var size struct{ rows, columns, x, y uint16 }
	if _, _, errno := syscall.Syscall(syscall.SYS_IOCTL, file.Fd(), syscall.TIOCGWINSZ, uintptr(unsafe.Pointer(&size))); errno == 0 && size.rows > 0 {
		return int(size.rows)
	}
	return 24
}
