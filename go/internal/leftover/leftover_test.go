package leftover

import (
	"cmp"
	"fmt"
	"maps"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"syscall"
	"testing"
)

// A process in the fake /proc: its stat's fields, its comm and its environment.
type faked struct {
	pid, parent, session int
	start                int64
	state, comm          string
	env                  []string
}

const home = "HOME=/home/acme"

// fakeProc makes a /proc holding these processes, its namespace 77, and the signals sent to
// them recorded in place of being sent; the grace is none, and the one seat ak has forgotten is
// `gone`.
func fakeProc(t *testing.T, processes ...faked) *[]string {
	root := t.TempDir()
	t.Setenv("HOME", "/home/acme")
	put := func(path, text string) {
		os.MkdirAll(filepath.Dir(path), 0o755)
		if err := os.WriteFile(path, []byte(text), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	os.MkdirAll(filepath.Join(root, "self", "ns"), 0o755)
	os.Symlink("pid:[77]", filepath.Join(root, "self", "ns", "pid"))
	for _, p := range processes {
		dir := filepath.Join(root, fmt.Sprint(p.pid))
		put(filepath.Join(dir, "stat"), fmt.Sprintf("%d (x y) %s %d %d %d 0 -1 0 0 0 0 0 0 0 0 0 20 0 1 0 %d 0",
			p.pid, cmp.Or(p.state, "S"), p.parent, p.session, p.session, p.start))
		put(filepath.Join(dir, "comm"), cmp.Or(p.comm, "sleep")+"\n")
		put(filepath.Join(dir, "environ"), strings.Join(p.env, "\x00")+"\x00")
		put(filepath.Join(dir, "cmdline"), "sleep\x00600 s\x00")
	}
	sent := &[]string{}
	was, waited, sending, forgetting := proc, grace, send, forgotten
	t.Cleanup(func() { proc, grace, send, forgotten = was, waited, sending, forgetting })
	proc, grace = root, 0
	forgotten = func() (func(string) bool, bool) { return func(tag string) bool { return tag == "gone" }, true }
	send = func(pid int, start int64, number syscall.Signal) bool {
		stat, ok := readStat(pid)
		*sent = append(*sent, fmt.Sprintf("%d %d", pid, number))
		return ok && stat.Start == start
	}
	return sent
}

// A gone `ak`'s process left in its session gets TERM, then, a look later, KILL, each logged; with
// no seat's tag to ask about, a home Go does not read is never read.
func TestWhatAGoneAkLeftInItsSessionEnds(t *testing.T) {
	sent := fakeProc(t, faked{pid: 31, session: 4, start: 900, env: []string{home, "AK_OWNER=77 4 800 4 ak usage"}})
	forgotten = func() (func(string) bool, bool) { return nil, false }
	var said []string
	if !Sweep(func(line string) { said = append(said, line) }) {
		t.Error("the sweep was left to Python")
	}
	if want := []string{"31 15", "31 9"}; !slices.Equal(*sent, want) {
		t.Errorf("sent %v, want %v", *sent, want)
	}
	if want := []string{
		"TERM to sleep '600 s' (pid 31), which a gone `ak usage` (pid 4) left running",
		"KILL to sleep '600 s' (pid 31), which a gone `ak usage` (pid 4) left running",
	}; !slices.Equal(said, want) {
		t.Errorf("logged %q", said)
	}
}

// Its `ak` having exited or another process now holding its pid, a process is left over too.
func TestAnExitedOrRecycledAkIsGone(t *testing.T) {
	for _, ak := range []faked{{pid: 4, session: 4, start: 800, state: "Z"}, {pid: 4, session: 4, start: 801}} {
		sent := fakeProc(t, ak, faked{pid: 31, session: 4, start: 900, env: []string{home, "AK_OWNER=77 4 800 4 ak usage"}})
		Sweep(func(string) {})
		if len(*sent) != 2 {
			t.Errorf("%+v: sent %v", ak, *sent)
		}
	}
}

// None of these is a leftover, those tagged not even with a forgotten seat's tag.
func TestWhatIsNeverALeftover(t *testing.T) {
	mark, tag := "AK_OWNER=77 4 800 4 ak usage", "AK_TMUX_OWNER=gone"
	for name, p := range map[string]faked{
		"its ak runs":         {pid: 4, session: 4, start: 800, env: []string{home, mark}},
		"a session its own":   {pid: 31, session: 31, start: 900, env: []string{home, mark}},
		"another namespace":   {pid: 31, session: 4, start: 900, env: []string{home, "AK_OWNER=78 4 800 4 ak usage"}},
		"exited":              {pid: 31, session: 4, start: 900, state: "Z", env: []string{home, mark, tag}},
		"a run's":             {pid: 31, session: 4, start: 900, env: []string{home, mark, tag, "AGENTKIT_RUN=/r"}},
		"another HOME's":      {pid: 31, session: 4, start: 900, env: []string{"HOME=/home/other", mark, tag}},
		"a tmux server":       {pid: 31, session: 4, start: 900, comm: "tmux: server", env: []string{home, mark, tag}},
		"below a tmux server": {pid: 31, parent: 20, session: 4, start: 900, env: []string{home, mark}},
		"unmarked":            {pid: 31, session: 4, start: 900, env: []string{home}},
		"a held seat's":       {pid: 31, session: 31, start: 900, env: []string{home, "AK_TMUX_OWNER=acme"}},
	} {
		sent := fakeProc(t, p, faked{pid: 20, parent: 31, session: 4, start: 1, comm: "tmux: server"})
		Sweep(func(string) {})
		if len(*sent) > 0 {
			t.Errorf("%s: sent %v", name, *sent)
		}
	}
}

// What a seat ak has forgotten left gets TERM, then KILL, each logged, wherever it runs: in a
// session of its own, below a tmux server, beside its mark's running `ak`. Each look reads the home
// once and asks it once of each seat, and ends what a gone `ak` left first.
func TestWhatAForgottenSeatLeftEnds(t *testing.T) {
	mark, tag := "AK_OWNER=77 4 800 4 ak usage", "AK_TMUX_OWNER=gone"
	sent := fakeProc(t,
		faked{pid: 4, session: 4, start: 800, env: []string{home, mark}},
		faked{pid: 20, session: 20, start: 1, comm: "tmux: server"},
		faked{pid: 31, session: 31, start: 900, env: []string{home, tag}},
		faked{pid: 32, parent: 20, session: 32, start: 900, env: []string{home, tag}},
		faked{pid: 33, session: 4, start: 900, env: []string{home, mark, tag}},
		faked{pid: 34, session: 4, start: 900, env: []string{home, "AK_OWNER=77 5 800 4 ak usage", tag}},
		faked{pid: 35, session: 35, start: 900, env: []string{home, "AK_TMUX_OWNER=acme"}})
	reads, asked := 0, map[string]int{}
	forgotten = func() (func(string) bool, bool) {
		reads++
		return func(tag string) bool { asked[tag]++; return tag == "gone" }, true
	}
	var said []string
	if !Sweep(func(line string) { said = append(said, line) }) {
		t.Error("the sweep was left to Python")
	}
	if want := []string{"34 15", "31 15", "32 15", "33 15", "34 9", "31 9", "32 9", "33 9"}; !slices.Equal(*sent, want) {
		t.Errorf("sent %v, want %v", *sent, want)
	}
	if want := "TERM to sleep '600 s' (pid 31), which a forgotten seat `gone` left running"; len(said) != 8 || said[1] != want {
		t.Errorf("logged %q", said)
	}
	if want := map[string]int{"gone": 2, "acme": 2}; reads != 2 || !maps.Equal(asked, want) {
		t.Errorf("read the home %d times, asked %v, want %v", reads, asked, want)
	}
}

// A seat's tag on a home Go does not read leaves the sweep to Python before anything is sent,
// what a gone `ak` left included.
func TestATagOnAHomeGoDoesNotReadIsPythons(t *testing.T) {
	sent := fakeProc(t,
		faked{pid: 31, session: 4, start: 900, env: []string{home, "AK_OWNER=77 4 800 4 ak usage"}},
		faked{pid: 32, session: 32, start: 900, env: []string{home, "AK_TMUX_OWNER=gone"}})
	forgotten = func() (func(string) bool, bool) { return nil, false }
	if Sweep(func(string) {}) || len(*sent) > 0 {
		t.Errorf("carried, sent %v", *sent)
	}
}

// Without /proc, as on a Mac, nothing is found and nothing waits.
func TestNoProcFindsNothing(t *testing.T) {
	sent := fakeProc(t)
	proc = filepath.Join(proc, "none")
	Sweep(func(string) {})
	if len(*sent) > 0 {
		t.Errorf("sent %v", *sent)
	}
}
