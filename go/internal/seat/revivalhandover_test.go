//go:build unix

package seat

import (
	"io"
	"os"
	"testing"
	"time"

	"agentkit/internal/notify"
	"agentkit/internal/run"
)

// A third death whose failure Go would not card, a login's news outranking it, is Python's whole:
// nothing of it is written before the tick hands over, its death included.
func TestARevivalFailureGoDoesNotCardHandsOverBeforeWriting(t *testing.T) {
	home, _ := questionRecoveryHome(t)
	record(t, home, "acme", map[string]any{"created": seconds(time.Now()) - 7200, "session_title": "acme"})
	t.Setenv("RECOVERY_HELD", "1")
	t.Setenv("AGENTKIT_DISCORD_USER_ID", "")
	write(t, stateFile(home, "watch.json"), `{"gh_out":{"at":100},"auth_out":{"claude":{"ok":false,"at":100,"why":"token expired"}}}`)
	write(t, stateFile(home, "seat-acme.json"), `{"word":"needs you","reason":"GitHub is logged out","state":"working"}`)
	if err := notify.Alert("acme", "acme (Claude) needs login: open the host, press this session's number, and log in again.", "auth:acme:claude:100", io.Discard); err != nil {
		t.Fatal(err)
	}
	if carried, err := notify.Turned("acme", CardLogin); !carried || err != nil {
		t.Fatal("the login alert was not carded", carried, err)
	}
	moment := time.Now()
	if err := Write("acme", "reopened_at", []any{run.Float(seconds(moment) - 1800), run.Float(seconds(moment) - 600)}); err != nil {
		t.Fatal(err)
	}
	found, known := TickHome(moment)
	if !known {
		t.Fatal("the fixture is not a home Go reads")
	}
	before := map[string]string{}
	for _, kind := range []string{"seat", "notify", "card"} {
		data, err := os.ReadFile(stateFile(home, kind+"-acme.json"))
		if err != nil {
			t.Fatal(err)
		}
		before[kind] = string(data)
	}
	if carried, err := found.ReviveTurns(moment, nil, func(string) {}, io.Discard); carried || err != nil {
		t.Fatal("Go carried a failure it does not card", carried, err)
	}
	for kind, want := range before {
		if data, err := os.ReadFile(stateFile(home, kind+"-acme.json")); err != nil || string(data) != want {
			t.Errorf("the handover wrote %s: before=%s after=%s %v", kind, want, data, err)
		}
	}
}
