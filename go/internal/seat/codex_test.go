package seat

import (
	"maps"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentkit/internal/commandhelp"
	"agentkit/internal/run"
)

func TestCodexScreenReadsTheThreadOnceTheTickBindsIt(t *testing.T) {
	home := sandbox(t)
	other := map[string]any{"conversation": "legacy", "id_source": nil, "repo": nil}
	record(t, home, "aaa", other)
	token := strings.Repeat("a", 32)
	fields := map[string]any{"orchestrator": "astra", "workers": []string{"astra"},
		"codex_launch": token, "conversation": nil, "id_source": nil, "resumable": false}
	record(t, home, "acme", fields)
	cwd, rollout := filepath.Join(home, "work", "acme"), filepath.Join(home, "rollout.jsonl")
	receipt := map[string]any{"launch": token, "cwd": cwd}
	writeReceipt := func() { write(t, stateFile(home, "codex-launch-"+token+".json"), encoded(t, receipt)) }
	writeReceipt()
	drawn(t, home, "acme", "Choose a model\n› 1. First\n  2. Second\n\n  Press enter to continue\n")
	checkScreen := func() Home {
		t.Helper()
		before := stateFiles(t, home)["session-acme.json"]
		lines := explained(t, "acme")
		if lines[0] != "acme  needs you" || lines[2] != "  authority: screen  rule: asking.chooser" {
			t.Fatal(lines)
		}
		if after := stateFiles(t, home)["session-acme.json"]; before != after {
			t.Fatalf("look changed the record: %s", after)
		}
		found, known := Looking(time.Now())
		if !known {
			t.Fatal("Go did not read the seat")
		}
		return found
	}
	waited := checkScreen() // prepare's chooser has no conversation yet
	write(t, rollout, encoded(t, map[string]any{"type": "session_meta", "payload": map[string]any{"id": "t1", "cwd": cwd}})+"\n")
	receipt["event"] = map[string]any{"hook_event_name": "SessionStart", "source": "startup",
		"session_id": "t1", "cwd": cwd, "transcript_path": rollout}
	writeReceipt()
	record(t, home, "aaa", other) // the earlier record has a reconcile to write too
	before := stateFiles(t, home)
	if _, known := Looking(time.Now()); known {
		t.Fatal("Go's look took a receipt no reconcile has bound")
	}
	if after := stateFiles(t, home); !maps.Equal(before, after) {
		t.Fatalf("handing over wrote: %v, then %v", before, after)
	}
	if _, _, err := waited.Explain("acme", time.Now()); err != nil {
		t.Fatalf("the receipt belongs to the next listing: %v", err)
	}
	if err := waited.Announce(time.Now()); err != nil {
		t.Fatalf("the receipt belongs to the next listing: %v", err)
	}
	if after := stateFiles(t, home)["session-acme.json"]; before["session-acme.json"] != after {
		t.Fatalf("listing changed the record: %s", after)
	}
	// The tick's reconcile binds the thread, and the next look reads the record it leaves.
	Reconcile()
	if bound, _ := run.ReadJSON(stateFile(home, "session-acme.json")); bound.Get("conversation") != "t1" ||
		bound.Get("id_source") != "codex-session-start" || bound.Get("resumable") != true {
		t.Fatalf("the tick did not bind the receipt: %s", run.Encode(bound))
	}
	waited = checkScreen()
	// A stale listing must never put t1 back over a newer conversation.
	fields["conversation"], fields["id_source"], fields["resumable"] = "t2", "codex-session-start", true
	record(t, home, "acme", fields)
	newer := stateFiles(t, home)["session-acme.json"]
	if err := waited.Announce(time.Now()); err != nil {
		t.Fatal(err)
	}
	if after := stateFiles(t, home)["session-acme.json"]; newer != after {
		t.Fatalf("listing overwrote the newer record: %s", after)
	}
}

func TestCodexReceiptAfterReconciliationWaitsForTheNextListing(t *testing.T) {
	for name, publish := range map[string]func(Home, string) error{
		"live look": func(_ Home, state string) error {
			_, err := LookedLive(state, "acme")
			return err
		},
		"why": func(home Home, _ string) error {
			_, _, err := home.Explain("acme", time.Now())
			return err
		},
		"list":               func(home Home, _ string) error { return home.Announce(time.Now()) },
		"after another word": func(home Home, _ string) error { return home.Announce(time.Now()) },
	} {
		t.Run(name, func(t *testing.T) {
			home := sandbox(t)
			record(t, home, "other", map[string]any{"created": 1})
			if name == "after another word" {
				drawn(t, home, "other", prompting)
			}
			token := strings.Repeat("a", 32)
			record(t, home, "acme", map[string]any{"orchestrator": "astra", "workers": []string{"astra"},
				"codex_launch": token, "conversation": nil, "id_source": nil, "resumable": false})
			drawn(t, home, "acme", "› Ask Codex to do anything\n\n  default default · ~\n")
			cwd, rollout := filepath.Join(home, "work", "acme"), filepath.Join(home, "rollout.jsonl")
			write(t, rollout, encoded(t, map[string]any{"type": "session_meta", "payload": map[string]any{"id": "t1", "cwd": cwd}})+"\n"+
				`{"type":"event_msg","payload":{"type":"task_complete","error":{"message":"stream disconnected"}}}`+"\n")
			launch := "codex-launch-" + token + ".json"
			prepared := encoded(t, map[string]any{"launch": token, "cwd": cwd})
			write(t, stateFile(home, launch), prepared)
			arrived := encoded(t, map[string]any{"launch": token, "cwd": cwd, "event": map[string]any{
				"hook_event_name": "SessionStart", "source": "startup", "session_id": "t1", "cwd": cwd, "transcript_path": rollout}})
			ready := filepath.Join(home, "receipt")
			write(t, ready, arrived)
			real, err := exec.LookPath("tmux")
			if err != nil {
				t.Fatal(err)
			}
			fake := filepath.Join(home, "bin", "tmux")
			when := `[ "$arg" = capture-pane ]`
			if name == "after another word" {
				when = `[ "$arg" = list-sessions ] && ` + commandhelp.ShellJoin([]string{"test", "-f", stateFile(home, "seat-other.json")})
			}
			write(t, fake, "#!/bin/sh\nfor arg do\n  if "+when+"; then\n    "+
				commandhelp.ShellJoin([]string{"cp", ready, stateFile(home, launch)})+"\n  fi\ndone\nexec "+
				commandhelp.ShellJoin([]string{real})+" \"$@\"\n")
			if err := os.Chmod(fake, 0o700); err != nil {
				t.Fatal(err)
			}
			t.Setenv("PATH", filepath.Dir(fake)+string(os.PathListSeparator)+os.Getenv("PATH"))
			found, known := Looking(time.Now())
			if !known {
				t.Fatal("Go did not read the prepared seat beside the other record")
			}
			before := stateFiles(t, home)
			if err := publish(found, stateFile(home, "")); err != nil {
				t.Fatalf("the capture's receipt belongs to the next listing: %v", err)
			}
			after := stateFiles(t, home)
			if after[launch] != arrived {
				t.Fatal("the hook did not arrive")
			}
			if after["session-acme.json"] != before["session-acme.json"] {
				t.Fatal("publishing the word changed the record")
			}
			file, _ := run.ReadJSON(stateFile(home, "seat-acme.json"))
			if file.Str("word") != "idle" || file.Str("rule") != "prompt.composer" || file.Get("stall") != nil {
				t.Fatalf("the word used evidence after reconciliation: %s", run.Encode(file))
			}
			if _, known := Looking(time.Now()); known {
				t.Fatal("the next listing must hand the receipt to Python")
			}
			if name == "after another word" {
				return
			}
			write(t, stateFile(home, launch), prepared)
			if lives, known := Lives(time.Now()); !known || len(lives) != 1 || lives[0].Stall != nil {
				t.Fatalf("the tick did not keep its initial evidence: known=%v, %+v", known, lives)
			}
		})
	}
}
