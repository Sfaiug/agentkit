package seat

import (
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
	program, err := os.Executable()
	if !ok || err != nil {
		return
	}
	pid, _ := paneReads(server, pane, "#{pane_pid}")
	cmd := exec.Command(program, "seat-look", seat, pid)
	cmd.Env = slices.DeleteFunc(os.Environ(), func(entry string) bool {
		return strings.HasPrefix(entry, "AK_OWNER=") || strings.HasPrefix(entry, "AK_TMUX_OWNER=")
	})
	host.Detach(cmd)
	if cmd.Start() == nil {
		cmd.Process.Release()
	}
}

// Look waits until the pane this process was started from no longer runs that process, as only
// then does tmux have the seat closed, and then looks as watch.hook_look does: only at a seat whose
// pane's socket and session are its own.  What it finds is written and told as every Go announce
// does (Seat.announce); where the look would do more than that, or Go does not read what it hangs
// on, nothing is (lookedAt).
func Look(launched, pid string) {
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
	name, _, err := config.ResolveSession(launched)
	if err != nil {
		return
	}
	said, err := tmux.Ask(tmux.Own(), "display-message", "-p", "-t", pane, "#{socket_path}\t#{session_name}")
	if err != nil || said != server+"\t"+name {
		return
	}
	lookAgain(filepath.Join(config.Home(), "state"), name, time.Now())
}

// lookAgain decides a seat tmux holds gone and tells what it finds, the deciding under its announce
// lock, so a look queued behind another announcer never lands an older word on that one's.
func lookAgain(state, name string, now time.Time) error {
	return announcing(state, name, func() error {
		if seat, models, known := lookedAt(state, name, now); known {
			return seat.announced(state, now, models)
		}
		return nil
	})
}
