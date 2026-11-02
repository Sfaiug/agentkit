package host

import (
	"context"
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
