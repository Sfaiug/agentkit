package seat

import (
	"errors"
	"maps"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentkit/internal/commandhelp"
)

func TestCodexScreenLeavesTheRecordForPythonToReconcile(t *testing.T) {
	home := sandbox(t)
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
	before := stateFiles(t, home)
	if _, known := Looking(time.Now()); known {
		t.Fatal("Go took a receipt Python has not bound")
	}
	if _, _, err := waited.Explain("acme", time.Now()); !errors.Is(err, ErrUnread) {
		t.Fatalf("a receipt arriving during the wait was looked past: %v", err)
	}
	if err := waited.Announce(time.Now()); !errors.Is(err, ErrUnread) {
		t.Fatalf("a listing looked past the new receipt: %v", err)
	}
	if after := stateFiles(t, home); !maps.Equal(before, after) {
		t.Fatalf("handing over wrote: %v, then %v", before, after)
	}
	// The next look reads the record Python's reconcile leaves.
	fields["conversation"], fields["id_source"], fields["resumable"] = "t1", "codex-session-start", true
	record(t, home, "acme", fields)
	waited = checkScreen()
	// A stale listing must never put t1 back over a newer conversation.
	fields["conversation"] = "t2"
	record(t, home, "acme", fields)
	newer := stateFiles(t, home)["session-acme.json"]
	if err := waited.Announce(time.Now()); err != nil {
		t.Fatal(err)
	}
	if after := stateFiles(t, home)["session-acme.json"]; newer != after {
		t.Fatalf("listing overwrote the newer record: %s", after)
	}
}

func TestCodexReceiptArrivingDuringCaptureIsHandedToPython(t *testing.T) {
	for name, publish := range map[string]func(Home, string) error{
		"live look": func(_ Home, state string) error {
			_, err := LookedLive(state, "acme")
			return err
		},
		"why": func(home Home, _ string) error {
			_, _, err := home.Explain("acme", time.Now())
			return err
		},
		"list": func(home Home, _ string) error { return home.Announce(time.Now()) },
	} {
		t.Run(name, func(t *testing.T) {
			home := sandbox(t)
			record(t, home, "other", map[string]any{"created": 1})
			token := strings.Repeat("a", 32)
			record(t, home, "acme", map[string]any{"orchestrator": "astra", "workers": []string{"astra"},
				"codex_launch": token, "conversation": nil, "id_source": nil, "resumable": false})
			drawn(t, home, "acme", "Choose a model\n› 1. First\n  2. Second\n\n  Press enter to continue\n")
			cwd, rollout := filepath.Join(home, "work", "acme"), filepath.Join(home, "rollout.jsonl")
			write(t, rollout, encoded(t, map[string]any{"type": "session_meta", "payload": map[string]any{"id": "t1", "cwd": cwd}})+"\n")
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
			write(t, fake, "#!/bin/sh\nfor arg do\n  if [ \"$arg\" = capture-pane ]; then\n    "+
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
			if err := publish(found, stateFile(home, "")); !errors.Is(err, ErrUnread) {
				t.Fatalf("the capture bypassed the new receipt: %v", err)
			}
			after := stateFiles(t, home)
			if after[launch] != arrived {
				t.Fatal("the hook did not arrive during capture")
			}
			before[launch] = arrived
			delete(after, "seat-acme.announce") // the empty lock the look took
			if !maps.Equal(before, after) {
				t.Fatalf("handing over wrote: %v, then %v", before, after)
			}
			write(t, stateFile(home, launch), prepared)
			if _, known := Lives(time.Now()); known {
				t.Fatal("the tick took a reading whose capture owes Python a reconcile")
			}
		})
	}
}
