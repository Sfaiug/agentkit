package seat

import (
	"maps"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/run"
)

func accountHome(t *testing.T) string {
	t.Helper()
	home := sandbox(t)
	write(t, filepath.Join(home, ".agentkit", "config.toml"), testConfig+"accounts=['default','second']\n")
	record(t, home, "acme", map[string]any{"account": "default", "session_title": "acme"})
	if err := os.MkdirAll(filepath.Join(home, "work", "acme"), 0o700); err != nil {
		t.Fatal(err)
	}
	accountMeters(t, home, 97, 10)
	return home
}

func accountMeters(t *testing.T, home string, current, other int) {
	t.Helper()
	reading := func(used int) *run.Object {
		return run.Fields("meters", []any{run.Fields("name", "session", "used", used, "window_secs", 18000,
			"resets_at", seconds(time.Now())+3600)})
	}
	write(t, stateFile(home, "usage.json"), run.Line(run.Fields("fetched_at", seconds(time.Now()),
		"providers", run.Fields("test", run.Fields("accounts", run.Fields("default", reading(current), "second", reading(other)))))))
}

func TestAccountRecoveryHandsOwnerInputTurnsAndWaitsBackWithoutWriting(t *testing.T) {
	for _, kind := range []string{"usage_wait", "usage_refusal", "midturn", "draft", "question", "flight", "recorded refusal", "no room"} {
		t.Run(kind, func(t *testing.T) {
			home := accountHome(t)
			pane := prompting
			switch kind {
			case "usage_wait", "usage_refusal", "midturn":
				write(t, stateFile(home, "seat-acme.json"), run.Line(run.Fields(kind, run.Fields("since", 1))))
			case "draft":
				pane = drafted
			case "question":
				pane = asked
			case "flight":
				write(t, stateFile(home, "hook-acme.json"), `{"event":"UserPromptSubmit","at":1800000000}`)
			case "recorded refusal":
				_, record, _ := config.ResolveSession("acme")
				chat, _ := harness.Conversation("claude", record)
				write(t, chat, `{"type":"assistant","isApiErrorMessage":true,"message":{"content":"API Error: 429 rate limit"}}`+"\n")
			case "no room":
				accountMeters(t, home, 100, 100)
			}
			drawn(t, home, "acme", pane)
			lives, known := Lives(time.Now())
			if !known || len(lives) != 1 {
				t.Fatal("a recovery case did not reach its account decision")
			}
			before := stateFiles(t, home)
			if carried, err := MoveAccount(lives[0], func(string) {}); carried || err != nil {
				t.Fatal(carried, err)
			}
			if !maps.Equal(before, stateFiles(t, home)) {
				t.Fatal("handover changed the seat")
			}
		})
	}
}

func TestTheLastAccountLookDefersRecentInputAndNewBackgroundWork(t *testing.T) {
	home := accountHome(t)
	drawn(t, home, "acme", prompting)
	lives, known := Lives(time.Now())
	if !known {
		t.Fatal("seat unread")
	}
	live := lives[0]
	if live.accountStill("acme", true) {
		t.Fatal("a recently used terminal moved between turns")
	}
	write(t, stateFile(home, "hook-acme.json"), `{"event":"Stop","holds":["monitor"],"at":1800000000}`)
	if live.accountStill("acme", true) {
		t.Fatal("new background work was cut off")
	}
	if !live.accountStill("acme", false) {
		t.Fatal("background work prevented a spent-account move")
	}
}

func TestReopeningKeepsANamedLoginAndUsesItsConversationStore(t *testing.T) {
	home := accountHome(t)
	_, record, _ := config.ResolveSession("acme")
	record["account"] = "second"
	chat, _ := harness.Conversation("claude", record)
	write(t, chat, "")
	back, known := comingBack(filepath.Join(home, ".agentkit", "state"), "acme", record, false, true)
	if !known || !back.opened || back.account != "second" || !strings.Contains(chat, ".claude-second") {
		t.Fatal("reopening lost its source subscription", known, back)
	}
}
