package seat

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/notify"
	"agentkit/internal/run"
	usages "agentkit/internal/usage"
)

// inboxWarmup is what a seat opened just now gets before it is typed into (watch.INBOX_WARMUP).
const inboxWarmup = 10 * time.Second

// AskInbox puts a passed review's merge question to the inbox seat and then to its owner, Python's
// watch.ask_inbox: the seat opened where none is up, the question typed at its quiet prompt under
// its lock, pinned to the commit reviewed, held back while an owner's question other than an
// earlier merge question stands, and its owner pinged once the seat took it.  `asked` is an
// earlier try's question taken, whose ping alone is owed; `typed` is told when this try's is.
// Sent once both have it; not carried where Go does not ask it, before anything is typed or written.
func AskInbox(question, url, sha string, asked bool, typed func(), log func(string), errOut io.Writer) (sent, carried bool) {
	name, _, err := config.ResolveSession(config.Inbox())
	if err != nil {
		return false, false
	}
	if !asked {
		own, opened := openInbox(name, log)
		if own == "" {
			return false, false
		}
		if opened {
			time.Sleep(inboxWarmup) // its harness has to be listening before it is typed into
		}
		line := fmt.Sprintf("%s -- %s at %s, reviewed by agentkit. The user was pinged with `ak notify needs`; wait for "+
			"their yes or no here. On yes run `gh pr merge %s --squash --delete-branch --match-head-commit %s` -- it "+
			"refuses if the author has pushed since the review, and then the PR needs a new review, not a merge; on no "+
			"leave the PR as it is and say so.", question, url, sha[:min(len(sha), 12)], url, sha)
		if (seatAt{name, own, "=" + name + ":"}).holds(keyed(line)) == "line" {
			return false, false // an earlier try left it in the composer: its Enter is Python's
		}
		if !typeAtPrompt(name, line, nil, func(*run.Object) error { return nil }, log, heldBack) {
			log("WARN could not type the question into the " + name + " seat")
			return false, true
		}
		log("asked the " + name + " seat: " + question)
		typed()
	}
	// a card Go cannot evaluate now leaves the ping owed: the question just typed kept on record for
	// the word to turn, an earlier try's Python's, nothing written for it
	pinged, err := notify.Needs(name, question, "inbox:"+url+":"+sha, !asked, notify.Looked(Published), errOut)
	return pinged && err == nil, pinged || err != nil || !asked
}

// heldBack is an owner's question standing in the seat that is no earlier merge question, which a
// merge question waits behind as recovery nudges do; read under the seat's lock.
func heldBack(name string) bool {
	notice := notify.Last(name)
	return notify.OwnerQuestion(notice) && !strings.HasPrefix(notice.Str("source"), "inbox:")
}

// openInbox opens the inbox seat where tmux holds none, Python's orch.ensure from cron: on the
// default selection, in ~/code, while its orchestrator has usage left of its own.  own is the
// harness the seat runs, "" where Go does not ask: Python refuses the name, would pick another
// model, or runs a harness Go does not type into; opened is a seat started now.
func openInbox(name string, log func(string)) (own string, opened bool) {
	names := ReadNames()
	if names.Seat(name) {
		if own, _ = seatHarness(name); typable(own) {
			return own, false
		}
		return "", false
	}
	picked, err := config.Defaults()
	models, unread := config.Models()
	readings, unmetered := usages.Read()
	own = models[picked.Orchestrator].Harness
	if names.Held(name) || err != nil || unread != nil || unmetered != nil ||
		readings.Spent(picked.Orchestrator) != "" || readings.OnCredits(picked.Orchestrator) || !typable(own) {
		return "", false
	}
	code := filepath.Join(config.UserHome(), "code")
	if err := os.MkdirAll(code, 0o777); err != nil {
		return "", false
	}
	started, err := Open(name, picked.Orchestrator, models, picked.Workers, code, false)
	if err != nil {
		log(fmt.Sprintf("WARN could not open the %s seat: %v", name, err))
		return own, false // the question fails at the seat and is asked again
	}
	if !started {
		return "", false
	}
	log(fmt.Sprintf("orch: started %s on %s", name, picked.Orchestrator))
	return own, true
}
