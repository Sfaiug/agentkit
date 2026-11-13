package seat

import (
	"fmt"
	"maps"
	"testing"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/harness"
)

func TestAMoveWaitsForAnEmptyInputField(t *testing.T) {
	for _, used := range []int{97, 100} {
		t.Run(fmt.Sprint(used, "% used"), func(t *testing.T) {
			home := accountHome(t)
			accountMeters(t, home, used, 10)
			_, record, _ := config.ResolveSession("acme")
			chat, _ := harness.Conversation("claude", record)
			write(t, chat, `{"type":"user","message":{"role":"user","content":"hello"}}`+"\n")
			accountAdapter(t, home, "case \"$1\" in auth) exit 0 ;; interactive) echo 'sleep 600' ;; esac\n")
			drawn(t, home, "acme", drafted)
			lives, known := Lives(time.Now())
			if !known || len(lives) != 1 {
				t.Fatal("seat unread")
			}
			before := stateFiles(t, home)
			carried, err := MoveAccount(lives[0], func(string) {})
			if !carried || err != nil {
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
