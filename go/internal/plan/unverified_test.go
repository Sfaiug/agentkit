package plan

import (
	"context"
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/lock"
)

func TestADeliveryStaysOwedUntilAVerificationChecksEveryLine(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	t.Setenv("USERPROFILE", os.Getenv("HOME"))
	state := filepath.Join(os.Getenv("HOME"), ".agentkit", "state")
	count := filepath.Join(state, "unverified-acme.txt")
	ctx := context.Background()
	if os.MkdirAll(state, 0o700) != nil || os.WriteFile(filepath.Join(state, "session-acme.json"), []byte(`{}`), 0o600) != nil {
		t.Fatal("no seat")
	}
	// another process verifies: the ending goes on, its delivery counted for that one to settle
	other, err := lock.Try(filepath.Join(state, "verify-acme.lock"))
	if err != nil {
		t.Fatal(err)
	}
	for range 2 {
		if err := Delivered(ctx, "acme", ""); err != nil {
			t.Fatal(err)
		}
	}
	if data, _ := os.ReadFile(count); string(data) != "2\n" {
		t.Fatalf("%q", data)
	}
	other.Close()
	// a line whose checkout is not on this host has no verdict: the count stays, and settles no further
	plan := "- [ ] it works · check: `true` · ~/code/gone#0123456789ab · written 2026-11-06 09:00\n"
	if os.WriteFile(filepath.Join(state, "plan-acme.md"), []byte(plan), 0o600) != nil {
		t.Fatal("no plan")
	}
	if err := Delivered(ctx, "acme", ""); err != nil || unverified("acme") != 3 {
		t.Fatalf("%v, %d owed", err, unverified("acme"))
	}
	// one that checked every line takes off what it read as it began, and the file goes with the last
	if os.Remove(filepath.Join(state, "plan-acme.md")) != nil {
		t.Fatal("plan kept")
	}
	if _, _, err := List(ctx, "acme", nil); err != nil { // no plan owes no check
		t.Fatal(err)
	}
	if _, err := os.Stat(count); !os.IsNotExist(err) {
		t.Fatalf("still owed: %v", err)
	}
}
