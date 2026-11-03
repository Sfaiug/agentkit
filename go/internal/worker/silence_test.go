package worker

import (
	"os"
	"path/filepath"
	"testing"
)

func TestOnlyWhatIsNoHeartbeatIsHeard(t *testing.T) {
	path := filepath.Join(t.TempDir(), "events.jsonl")
	heard := Heard(path, []string{"keepalive"})
	write := func(text string) {
		file, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0o666)
		if err != nil {
			t.Fatal(err)
		}
		defer file.Close()
		file.WriteString(text)
	}
	before := heard()
	write(`{"type": "keepalive"}` + "\n")
	if heard() != before {
		t.Fatal("a heartbeat is no activity")
	}
	write(`{"type": "text"}` + "\n" + `{"type": "te`)
	if heard() == before {
		t.Fatal("an event is activity")
	}
}
