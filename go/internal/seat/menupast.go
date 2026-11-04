package seat

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/harness"
	"agentkit/internal/run"
	"agentkit/internal/tmux"
)

// A stopped seat's old rulebook decides no row; removal takes it and reopening writes it anew.
func pastKind(state, name, kind, suffix string) bool {
	if kind != "rulebook" || suffix != "md" {
		return false
	}
	file, err := run.ReadJSON(filepath.Join(state, "seat-"+name+".json"))
	closed, known := stopped(file)
	return err == nil && known && closed
}

// PastReady offers only seats both the shared stop and the harness's launch carry. A notice,
// even one already seen, needs Python's opening baseline; retained run checkouts need its stop.
func (seat Seat) PastReady(now time.Time) (closed float64, restart string, known bool) {
	_, file, known := pastReopening(seat.Name, now)
	if !known {
		return 0, "", false
	}
	closed, _ = file.Num("stopped_at")
	return closed, seat.restart, true
}

func pastReopening(name string, now time.Time) (reopening, *run.Object, bool) {
	state := filepath.Join(config.Home(), "state")
	found, known := look(state, name, now)
	if !known || found.live || !found.recorded || !found.closed {
		return reopening{}, nil, false
	}
	if _, err := os.Lstat(filepath.Join(state, "notify-"+name+".json")); !os.IsNotExist(err) {
		return reopening{}, nil, false
	}
	current, record, err := config.ResolveSession(name)
	file, unread := run.ReadJSON(seatFile(name))
	closed, stoppedKnown := stopped(file)
	if err != nil || current != name || record == nil || unread != nil || !stoppedKnown || !closed {
		return reopening{}, nil, false
	}
	// The common admission reads models, efforts, ownership and the harness's own store.
	seat, known := comingBack(state, name, record, false, true)
	_, opens := harness.Opens(seat.model.Harness)
	if !known || !opens {
		return reopening{}, nil, false
	}
	if _, err := os.Lstat(filepath.Join(seat.cwd, ".git")); !os.IsNotExist(err) && !dirsOf(seat.cwd).known {
		return reopening{}, nil, false
	}
	// A project's first fetch still belongs to Python. An unconfigured repository has none.
	if repo, _ := record["repo"].(string); repo != "" {
		g := gitcall.Git{Repo: repo, Env: gitcall.ProjectEnv(repo)}
		ref, err := g.Try("rev-parse", "--verify", "--quiet", rulesRef)
		origin, unread := g.Try("remote", "get-url", "origin")
		if err != nil || unread != nil || ref == "" && origin != "" {
			return reopening{}, nil, false
		}
	}
	return seat, file, true
}

// ReopenPast lends the menu's terminal to the stopped seat, on the same command and launch as
// Reopen. An adapter with no command leaves its stop mark intact and names the model in a note.
func ReopenPast(name string, dry bool, out, errOut io.Writer) (bool, error) {
	seat, _, known := pastReopening(name, time.Now())
	if !known {
		return false, nil
	}
	settled, known, err := seat.relaunch(dry, out)
	if !known {
		return true, Refusal(fmt.Sprintf("could not reopen %s on %s", name, seat.orchestrator))
	}
	if err != nil || dry {
		return true, err
	}
	return true, attachTerminal(settled, out, errOut, tmux.Visit)
}
