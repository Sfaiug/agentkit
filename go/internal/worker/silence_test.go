package worker

import (
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestAWatchSaysWhatEndedItsContext(t *testing.T) {
	path := filepath.Join(t.TempDir(), "activity")
	said := false
	ctx, ended := Watch{Silence: time.Second, Heard: Written(path), Before: func() { said = true }}.Stop(context.Background())
	<-ctx.Done()
	if why := ended(); why != "silence" || !said {
		t.Fatalf("got %q, before ran: %v", why, said)
	}
	ctx, ended = Watch{Silence: time.Hour, Ceiling: time.Second, Heard: Written(path)}.Stop(context.Background())
	<-ctx.Done()
	if why := ended(); why != "ceiling" {
		t.Fatalf("got %q", why)
	}
	outer, cancel := context.WithCancel(context.Background())
	ctx, ended = Watch{Silence: time.Hour, Heard: Written(path)}.Stop(outer)
	cancel()
	<-ctx.Done()
	if why := ended(); why != "" {
		t.Fatalf("got %q", why)
	}
	if ctx, ended := (Watch{}).Stop(context.Background()); ctx.Err() != nil || ended() != "" {
		t.Fatal("nothing to watch ends nothing")
	}
}

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
