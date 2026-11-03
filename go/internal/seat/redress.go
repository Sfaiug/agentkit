package seat

import (
	"os"
	"path/filepath"
	"time"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/tmux"
)

// PublishVerb is the hidden verb a seat's redress hands its bar to, `ak seat-look <seat>`.
const PublishVerb = "seat-look"

// Redress rewrites the bar of the seat that launched a run now, as Python's handback.redress_seat
// does at a run's launch, each step and its ending: every open menu hears first, through the one
// file they watch, then a `run-shell -b` job on the seats' own server publishes the seat
// (Publish), so the run waits on neither the seat's lock nor tmux past a second.  The job is the
// server's, which the run's exit leaves be; a seat tmux has lost runs none, and nothing here fails
// the run, whose next step or tick repairs a missed update.
func Redress(name string) {
	if name == "" {
		return
	}
	if config.EnsureDirs() == nil {
		moved := filepath.Join(config.Home(), "state", "runs-moved")
		if file, err := os.OpenFile(moved, os.O_WRONLY|os.O_CREATE, 0o666); err == nil {
			file.Close()
			now := time.Now()
			os.Chtimes(moved, now, now)
		}
	}
	program, err := os.Executable()
	if err != nil {
		return
	}
	// silent and always 0: tmux shows a job's output, or its failure, in the seat's pane
	job := commandhelp.ShellJoin([]string{program, PublishVerb, name}) + " >/dev/null 2>&1; true"
	tmux.AskWithin(time.Second, tmux.Own(), "run-shell", "-b", "-t", "="+name+":", tmux.Literal(job))
}

// Publish is Redress's job, Python's publish_seat: that seat's word and bar, where tmux holds it
// on ak's own server and Go reads it.  Go publishes a seat through its look (LookedLive), the one
// announce it has for a seat its panes run on; one Go does not read is the tick's.
func Publish(name string) {
	LookedLive(filepath.Join(config.Home(), "state"), name)
}
