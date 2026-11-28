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

func TestABoundLiveAsTheSilenceReachesItsLimitHoldsItOff(t *testing.T) {
	const silence = 1050 * time.Millisecond // reached just after a look, a second before the next
	end := time.Now().Add(1950 * time.Millisecond)
	var stopped time.Time
	ctx, ended := Watch{Silence: silence, Heard: Written(filepath.Join(t.TempDir(), "activity")),
		Declared: func(now float64) bool { return now < float64(end.UnixNano())/1e9 },
		Before:   func() { stopped = time.Now() }}.Stop(context.Background())
	<-ctx.Done()
	if why := ended(); why != "silence" || stopped.Sub(end) < silence {
		t.Fatalf("got %q %v after the bound's end", why, stopped.Sub(end))
	}
}
