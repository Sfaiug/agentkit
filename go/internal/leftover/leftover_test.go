package leftover

import (
	"cmp"
	"fmt"
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
// them recorded in place of being sent; the grace is none.
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
	was, waited, sending := proc, grace, send
	t.Cleanup(func() { proc, grace, send = was, waited, sending })
	proc, grace = root, 0
	send = func(pid int, start int64, number syscall.Signal) bool {
		stat, ok := readStat(pid)
		*sent = append(*sent, fmt.Sprintf("%d %d", pid, number))
		return ok && stat.Start == start
	}
	return sent
}

// A gone `ak`'s process left in its session gets TERM, then, a look later, KILL, each logged.
func TestWhatAGoneAkLeftInItsSessionEnds(t *testing.T) {
	sent := fakeProc(t, faked{pid: 31, session: 4, start: 900, env: []string{home, "AK_OWNER=77 4 800 4 ak usage"}})
	var said []string
	Sweep(func(line string) { said = append(said, line) })
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

// None of these is a leftover, and with no tag among them Go carries the sweep.
func TestWhatIsNeverALeftover(t *testing.T) {
	mark := "AK_OWNER=77 4 800 4 ak usage"
	for name, p := range map[string]faked{
		"its ak runs":         {pid: 4, session: 4, start: 800, env: []string{home, mark}},
		"a session its own":   {pid: 31, session: 31, start: 900, env: []string{home, mark}},
		"another namespace":   {pid: 31, session: 4, start: 900, env: []string{home, "AK_OWNER=78 4 800 4 ak usage"}},
		"exited":              {pid: 31, session: 4, start: 900, state: "Z", env: []string{home, mark}},
		"a run's":             {pid: 31, session: 4, start: 900, env: []string{home, mark, "AGENTKIT_RUN=/r"}},
		"another HOME's":      {pid: 31, session: 4, start: 900, env: []string{"HOME=/home/other", mark}},
		"a tmux server":       {pid: 31, session: 4, start: 900, comm: "tmux: server", env: []string{home, mark}},
		"below a tmux server": {pid: 31, parent: 20, session: 4, start: 900, env: []string{home, mark}},
		"unmarked":            {pid: 31, session: 4, start: 900, env: []string{home}},
	} {
		sent := fakeProc(t, p, faked{pid: 20, parent: 31, session: 4, start: 1, comm: "tmux: server"})
		Sweep(func(string) {})
		if len(*sent) > 0 || !Tagless() {
			t.Errorf("%s: sent %v", name, *sent)
		}
	}
}

// A seat's tag is Python's to judge, unless the process is one the sweep never ends.
func TestATagIsForPython(t *testing.T) {
	fakeProc(t, faked{pid: 31, session: 31, start: 900, env: []string{home, "AK_TMUX_OWNER=acme"}})
	if Tagless() {
		t.Error("a tagged process went unseen")
	}
	fakeProc(t, faked{pid: 31, session: 4, start: 900, env: []string{home, "AK_OWNER=77 4 800 4 ak usage", "AK_TMUX_OWNER=acme"}})
	if Tagless() {
		t.Error("a leftover's tag went unseen")
	}
	fakeProc(t, faked{pid: 31, session: 31, start: 900, env: []string{"HOME=/home/other", "AK_TMUX_OWNER=acme"}})
	if !Tagless() {
		t.Error("another HOME's tag counted")
	}
}

// Without /proc, as on a Mac, nothing is found and nothing waits.
func TestNoProcFindsNothing(t *testing.T) {
	sent := fakeProc(t)
	proc = filepath.Join(proc, "none")
	Sweep(func(string) {})
	if len(*sent) > 0 || !Tagless() {
		t.Errorf("sent %v", *sent)
	}
}
