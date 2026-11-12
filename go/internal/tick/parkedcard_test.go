//go:build unix

package tick

import (
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentkit/internal/notify"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// parkedHome holds seat acme on Claude Code, watched, and its run fix-api parked as stalled at
// review with nobody told; its pane shows $HOME/pane and takes no key.
func parkedHome(t *testing.T) string {
	t.Helper()
	ak, _ := goneHome(t)
	bin := strings.Split(os.Getenv("PATH"), string(os.PathListSeparator))[0]
	put(t, filepath.Join(bin, "tmux"), `#!/bin/sh
case "$*" in
  *list-sessions*) printf 'acme\t1\n' ;;
  *list-panes*) printf '%%1 0\n' ;;
  *capture-pane*) cat "$HOME/pane" ;;
  *'#{pane_id}'*) printf '%%1\t1\t1\n' ;;
  *'#{session_attached}'*'#{session_activity}'*) printf '0\t1\n' ;;
  *'#{session_attached}'*) printf '0\n' ;;
  *'#{session_created}'*) printf '1\n' ;;
  *send-keys*) exit 99 ;;
esac
`)
	path := filepath.Join(ak, "runs", "fix-api", "run.json")
	put(t, path, `{"run_id":"fix-api","state":"stalled","launched_session":"acme","finished_at":null,"stalls":[{"step":"review"}],"stalled_notified":false}`)
	return ak
}

// A card Go does not send for a line its seat did not take leaves the tick to Python before
// anything is written: no notice, no word published, the run untold.
func TestARefusedParkedCardHandsOverWritingNothing(t *testing.T) {
	for _, refusal := range []string{"native chooser", "owner closed", "completed card", "undated card"} {
		t.Run(refusal, func(t *testing.T) {
			ak := parkedHome(t)
			pane := "────────\n❯ fix the build\n────────\n  ⏵⏵ bypass permissions on (shift+tab to cycle)\n"
			if refusal == "native chooser" {
				pane = "Which database?\nEnter to select · ↑/↓ to navigate · Esc to cancel\n"
			}
			put(t, filepath.Join(os.Getenv("HOME"), "pane"), pane)
			if !seat.Watching("acme") {
				t.Fatal("the seat is not watched")
			}
			line := "run fix-api stalled three times at review; parked: ak run resume fix-api"
			file := run.Fields("state", "draft", "word", "needs you", "reason", line)
			switch refusal {
			case "native chooser":
				file.Set("state", "asking")
			case "owner closed":
				file.Set("closed_by_owner", true)
			case "completed card":
				put(t, filepath.Join(ak, "state", "card-acme.json"), `{"word":"done"}`)
			case "undated card":
				put(t, filepath.Join(ak, "state", "card-acme.json"), `{"word":"needs you","since":null}`)
			}
			put(t, filepath.Join(ak, "state", "seat-acme.json"), run.Line(file))
			if carried, err := notify.Needs("acme", line, "stalled:fix-api:review", false, seat.Published, io.Discard); carried || err != nil {
				t.Fatalf("the card is not refused: %v, %v", carried, err)
			}
			beforeSeat := read(t, filepath.Join(ak, "state", "seat-acme.json"))
			beforeSession := read(t, filepath.Join(ak, "state", "session-acme.json"))
			tick := &ticking{log: newLog(io.Discard, io.Discard), clock: time.Now}
			err := tick.tellParked(filepath.Join(ak, "runs", "fix-api"))
			if !errors.Is(err, errLeft) {
				t.Fatalf("a refused card did not hand over: %v", err)
			}
			record, err := run.ReadJSON(filepath.Join(ak, "runs", "fix-api", "run.json"))
			if err != nil || record.Truthy("stalled_notified") {
				t.Fatal("a refused card marked the run told", record, err)
			}
			path := filepath.Join(ak, "state", "notify-acme.json")
			if notice, err := os.ReadFile(path); !os.IsNotExist(err) {
				t.Errorf("a refused card wrote %s before handing over: %s (%v)", path, notice, err)
			}
			if after := read(t, filepath.Join(ak, "state", "seat-acme.json")); after != beforeSeat {
				t.Errorf("a refused card published the seat: %s", after)
			}
			if after := read(t, filepath.Join(ak, "state", "session-acme.json")); after != beforeSession {
				t.Errorf("a refused card changed the seat's record: %s", after)
			}
		})
	}
}
