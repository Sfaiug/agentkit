package seat

import (
	"fmt"
	"maps"
	"path/filepath"
	"testing"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/harness"
)

func TestAMoveWaitsForAnEmptyInputFieldButWhereAksEditorCarriesASpentAccountsDraft(t *testing.T) {
	for _, used := range []int{97, 100} {
		for _, editor := range []bool{false, true} {
			t.Run(fmt.Sprint(used, "% used, ak's editor ", editor), func(t *testing.T) {
				home := accountHome(t)
				accountMeters(t, home, used, 10)
				_, record, _ := config.ResolveSession("acme")
				chat, _ := harness.Conversation("claude", record)
				write(t, chat, `{"type":"user","message":{"role":"user","content":"hello"}}`+"\n")
				accountAdapter(t, home, "case \"$1\" in auth) exit 0 ;; interactive) echo 'sleep 600' ;; esac\n")
				visual := ""
				if editor {
					visual = filepath.Join(config.Repo(), "tools", "aside-editor")
				}
				t.Setenv("VISUAL", visual) // the pane's, as the tmux server it starts hands it on
				drawn(t, home, "acme", drafted)
				lives, known := Lives(time.Now())
				if !known || len(lives) != 1 {
					t.Fatal("seat unread")
				}
				before := stateFiles(t, home)
				carried, err := MoveAccount(lives[0], false, func(string) {})
				if carried != (used < 100 || !editor) || err != nil {
					t.Fatal(carried, err)
				}
				after := stateFiles(t, home)
				delete(after, "watch.lock") // the lock the field is read under, as Python's
				if !maps.Equal(before, after) {
					t.Fatal("a move over a draft changed the seat")
				}
			})
		}
	}
}
