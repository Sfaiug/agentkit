package handback

import (
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"

	"agentkit/internal/lock"
	"agentkit/internal/run"
)

func TestAPrintedRefusalWaitsForADeliveryUnderWay(t *testing.T) {
	dir := filepath.Join(seated(t), ".agentkit", "runs", "refused")
	if err := os.MkdirAll(dir, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := run.Create(dir, run.Fields("state", "error", "error", "split it", "launched_session", "acme", "reported", false)); err != nil {
		t.Fatal(err)
	}
	held, err := lock.Wait(context.Background(), filepath.Join(dir, "delivery.lock"))
	if err != nil {
		t.Fatal(err)
	}
	done := make(chan error, 1)
	go func() { done <- PrintedAtLaunch(dir, func(string) {}) }()
	select {
	case <-done:
		t.Fatal("marked while another delivery held the run's delivery lock")
	case <-time.After(200 * time.Millisecond):
	}
	held.Close()
	if err := <-done; err != nil {
		t.Fatal(err)
	}
	if after, _ := run.Read(dir); !after.Truthy("handed_back") || !after.Truthy("reported") || after.Str("handback_note") != printedNote {
		t.Fatalf("not marked handed back: %s", run.Line(after))
	}
}
