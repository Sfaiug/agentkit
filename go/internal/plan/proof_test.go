package plan

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"testing"
	"time"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
)

// A features list printed whole is read though a child it left holds the output open, as
// Python's communicate reads it within the deadline.
func TestAListAChildHoldsOpenStillRefusesAnUnprovenRetirement(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	checkout := t.TempDir()
	tool := filepath.Join(checkout, "features")
	since := time.Now().Add(-72 * time.Hour).UTC().Format(time.RFC3339)
	script := fmt.Sprintf("#!/bin/sh\necho '[{\"id\": \"analytics_events\", \"everyone\": true, \"everyone_since\": \"%s\"}]'\nsleep 2 &\n", since)
	if err := os.WriteFile(tool, []byte(script), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(checkout, "AGENTS.md"), []byte("---\nfeatures: "+tool+"\n---\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	check := `python3 -c "import sys; sys.path.insert(0, ` + commandhelp.Quote(config.Repo()) +
		`); from agentkit import retire; retire.check_main()" analytics_events proven`
	if unproven(context.Background(), checkout, check) == nil {
		t.Fatal("a switch on for everyone three days was taken as proven")
	}
}
