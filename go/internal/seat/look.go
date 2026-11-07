package seat

import (
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/host"
	"agentkit/internal/tmux"
)

// paneOf is the server and pane a named seat's wrapper runs in, or false outside one: only a
// seat's own pane, on its own server, has a word for a look to move (idle-compact.seat_looks).
func paneOf() (seat, server, pane string, ok bool) {
	seat = os.Getenv("AGENTKIT_SESSION")
	server, _, _ = strings.Cut(os.Getenv("TMUX"), ",")
	pane = os.Getenv("TMUX_PANE")
	return seat, server, pane, seat != "" && !strings.Contains(seat, "/") && seat != "." && seat != ".." && server != "" && pane != ""
}

// paneReads is what tmux expands that format to for this pane; an error where it cannot say.
func paneReads(server, pane, form string) (string, error) {
	return tmux.Ask(tmux.Default, "-S", server, "display-message", "-p", "-t", pane, form)
}

// StartLook has the seat this wrapper runs in looked at again, without waiting for it, as its
// harness has exited (watch.start_look, `ending`): `ak seat-look` in a session of its own, with no
// stdin or stdout and neither of ak's marks, so that ending this wrapper ends none of it.  Outside
// a named seat's pane it starts nothing.
func StartLook() {
	seat, server, pane, ok := paneOf()
	if !ok {
		return
	}
	pid, _ := paneReads(server, pane, "#{pane_pid}")
	if look := startLook(seat, pid); look != nil {
		look.Process.Release()
	}
}

// startLook is the look at that seat, once the pane no longer runs that process, started as a
// process of its own: nil where none could start.
func startLook(seat, pid string) *exec.Cmd {
	cmd, err := lookCommand(seat, pid)
	if err != nil || cmd.Start() != nil {
		return nil
	}
	return cmd
}

// lookCommand is `ak seat-look` with those arguments, with no stdin or stdout, neither of ak's marks,
// and a session of its own.
func lookCommand(args ...string) (*exec.Cmd, error) {
	program, err := os.Executable()
	if err != nil {
		return nil, err
	}
	cmd := exec.Command(program, append([]string{"seat-look"}, args...)...)
	cmd.Env = slices.DeleteFunc(os.Environ(), func(entry string) bool {
		return strings.HasPrefix(entry, "AK_OWNER=") || strings.HasPrefix(entry, "AK_TMUX_OWNER=")
	})
	host.Detach(cmd)
	return cmd, nil
}

// Look waits until the pane this process was started from no longer runs that process, as only
// then does tmux have the seat closed, where it names one, and then looks as watch.hook_look does:
// only at a seat whose pane's socket and session are its own.  A seat Go reads alive has the answer
// to its question recorded first, the prompt `heard` among what may answer it.  What it finds, on the
// screen of a seat whose panes run on or else as a seat gone, is written and told as every Go
// announce does (Seat.announce); where the look would do more than that, or Go does not read what it
// hangs on, nothing is (LookedLive, lookedAt).  A turn its harness says failed settles its account
// first, which is the tick's in Go: this look leaves it.
func Look(launched, pid string, heard *Prompt) {
	_, server, pane, ok := paneOf()
	if !ok {
		return
	}
	for pid != "" {
		if said, err := paneReads(server, pane, "#{pane_dead} #{pane_pid}"); err != nil || said != "0 "+pid {
			break
		}
		time.Sleep(50 * time.Millisecond)
	}
	name, own := inPane(launched)
	if !own {
		return
	}
	state := filepath.Join(config.Home(), "state")
	home, live, known := liveSeat(name, time.Now(), lookRuns, nil)
	if !known {
		lookAgain(state, name)
		return
	}
	if failed(name, live.own) || answering(state, name, heard) != nil {
		return
	}
	if _, err := lookedLive(state, name, home.runs, home.readers); errors.Is(err, ErrUnread) {
		lookAgain(state, name)
	}
}

// inPane is the name that seat goes by now, and whether this process runs in its own pane, on the
// seat's own server, as watch.hook_look checks: a harness under some other tmux, or a test's sandbox
// with a seat's name in its environment, never moves a real seat's bar or answers its question.
func inPane(launched string) (string, bool) {
	_, server, pane, ok := paneOf()
	name, _, err := config.ResolveSession(launched)
	if !ok || err != nil {
		return "", false
	}
	said, err := tmux.Ask(tmux.Own(), "display-message", "-p", "-t", pane, "#{socket_path}\t#{session_name}")
	return name, err == nil && said == server+"\t"+name
}

// lookAgain decides a seat tmux holds gone and tells what it finds, the deciding and its clock
// under its announce lock, so a look queued behind another announcer never lands an older word on
// that one's, nor reads what was recorded while it queued as still to come.
func lookAgain(state, name string) error {
	return announcing(state, name, func() error {
		now := time.Now()
		if seat, models, known := lookedAt(state, name, now); known {
			return seat.announced(state, now, models)
		}
		return nil
	})
}
