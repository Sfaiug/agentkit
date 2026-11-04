//go:build unix

package notify

import (
	"io"
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

func questionHome(t *testing.T) (string, func(string, string)) {
	t.Helper()
	home, bin := t.TempDir(), t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("PATH", bin)
	t.Setenv("AK_NOTIFY_SINK", "dry-run")
	t.Setenv("AK_RUN_ROLE", "")
	t.Setenv("AGENTKIT_ADAPTER_DIR", "")
	t.Setenv("AGENTKIT_DISCORD_USER_ID", "")
	write := func(path, text string) {
		t.Helper()
		if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(text), 0o700); err != nil {
			t.Fatal(err)
		}
	}
	write(filepath.Join(bin, "tmux"), "#!/bin/sh\nprintf '0\\t1\\n'\n")
	write(filepath.Join(home, ".agentkit", "config.toml"), "[models.opus]\nharness='claude'\nmodel='claude-opus'\neffort='high'\nprovider='test'\n[providers.test]\nmode='subscription'\n")
	write(seatFile("session", "acme", "json"), `{"orchestrator":"opus","cwd":"/code/acme","conversation":"conv-acme"}`)
	return home, write
}

func TestQuestionCardsLeaveOtherTransitionsToPython(t *testing.T) {
	for _, kind := range []string{"answered", "typed answer", "earlier answer", "watcher", "chooser", "other reason", "closed", "done", "history"} {
		t.Run(kind, func(t *testing.T) {
			home, write := questionHome(t)
			notice := run.Fields("kind", "needs", "text", "Which database?", "time", 100)
			file := run.Fields("word", "needs you", "reason", "Which database?", "state", "at_prompt")
			card := episode(run.NewObject(), "needs you", run.Number("100"), run.Number("100"))
			write(seatFile("notify", "acme", "json"), run.Line(notice))
			if !UnansweredQuestion("acme") {
				t.Fatal("the fixture's question was not readable before the handover condition")
			}
			switch kind {
			case "answered":
				notice.Set("answered_at", 200)
			case "typed answer":
				write(filepath.Join(home, ".claude", "projects", "-code-acme", "conv-acme.jsonl"),
					`{"type":"user","timestamp":"2026-11-01T00:00:00Z","message":{"role":"user","content":"Use the first"}}`+"\n")
			case "earlier answer":
				notice.Set("earlier_answer_at", 200)
			case "watcher":
				notice.Set("watcher", true)
			case "chooser":
				file.Set("state", "asking")
			case "other reason":
				file.Set("reason", "waiting on login")
			case "closed":
				file.Set("closed_by_owner", true)
			case "done":
				card.Set("word", "done")
			case "history":
				write(filepath.Join(state(), "installed-at"), "200\n")
			}
			before := map[string]string{}
			for kind, object := range map[string]*run.Object{"notify": notice, "seat": file, "card": card} {
				path := seatFile(kind, "acme", "json")
				before[path] = run.Line(object)
				write(path, before[path])
			}
			if carried, err := TurnedQuestion("acme", func(string) (string, any) { return "needs you", run.Number("100") }, io.Discard); carried || err != nil {
				t.Fatalf("carried=%v: %v", carried, err)
			}
			for path, want := range before {
				if after, err := os.ReadFile(path); err != nil || string(after) != want {
					t.Fatalf("handover changed %s: %s, %v", path, after, err)
				}
			}
			if _, err := os.Stat(outbox()); !os.IsNotExist(err) {
				t.Fatal("handover made an outbox")
			}
		})
	}
}

func TestAWorkerTickCardsNothing(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	t.Setenv("AK_RUN_ROLE", "worker")
	if carried, err := TurnedQuestion("acme", func(string) (string, any) {
		t.Fatal("a worker read a card to page")
		return "", nil
	}, io.Discard); !carried || err != nil {
		t.Fatal(carried, err)
	}
	if _, err := os.Stat(state()); !os.IsNotExist(err) {
		t.Fatal("a worker wrote notification state")
	}
}
