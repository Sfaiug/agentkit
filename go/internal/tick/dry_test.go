//go:build unix

package tick

import (
	"bytes"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"runtime"
	"strings"
	"testing"
	"time"

	"agentkit/internal/harness"
	"agentkit/internal/host"
	"agentkit/internal/run"
	"agentkit/internal/tmux"
)

// A home holding nothing but the PRs it follows is answered, its GitHub passes run dry where gh is
// logged in; anything a pass would act on leaves the dry run to Python with nothing printed.
func TestDryLeavesToPythonWhatItWouldActOn(t *testing.T) {
	home := t.TempDir()
	bin := t.TempDir()
	for key, value := range map[string]string{
		"HOME": home, "USERPROFILE": home, "TMUX_TMPDIR": t.TempDir(), "AGENTKIT_TMUX_SOCKET": "dry-test",
		"AGENTKIT_SESSION": "", "AGENTKIT_ADAPTER_DIR": "", "PATH": bin + string(os.PathListSeparator) + os.Getenv("PATH"),
	} {
		t.Setenv(key, value)
	}
	gh := func(script string) {
		if err := os.WriteFile(filepath.Join(bin, "gh"), []byte("#!/bin/sh\n"+script+"\n"), 0o700); err != nil {
			t.Fatal(err)
		}
	}
	dry := func(want bool) string {
		t.Helper()
		var out bytes.Buffer
		if Dry(&out) != want || !want && out.Len() > 0 {
			t.Fatalf("answered %v, printing %q", !want, out.String())
		}
		return out.String()
	}
	gh("echo 'To get started, please run:\n\n  gh auth login' >&2; exit 4")
	put(t, filepath.Join(home, ".agentkit", "state", "watch.json"), `{"own": {"https://github.com/acme/api/pull/1": {}}}`)
	if got := dry(true); got != "lock free · no tick has ended yet · watch.log 0.0 MB of 5 MB\ngh is not logged in; PR checks skipped (To get started, please run: gh auth login)\n" {
		t.Fatalf("printed %q", got)
	}
	if err := os.RemoveAll(filepath.Join(home, ".agentkit")); err != nil {
		t.Fatal(err)
	}
	// each a folder holding the file named
	for found, content := range map[string]string{"runs/fix-api/run.json": `{"state":"waiting_login"}`, "jobs/fix-api/job.json": `{"tasks": [{"name": "fix-api.md", "state": "queued"}]}`, "state/notification-outbox/acme.json": ""} {
		path := filepath.Join(home, ".agentkit", found)
		if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
			t.Fatal(err)
		}
		dry(false)
		if err := os.RemoveAll(filepath.Join(home, ".agentkit")); err != nil {
			t.Fatal(err)
		}
	}
	t.Setenv("AGENTKIT_SESSION", "acme")
	dry(false)
	t.Setenv("AGENTKIT_SESSION", "")
	gh(`echo '{"login": "acme"}'`)
	if got := dry(true); got != "lock free · no tick has ended yet · watch.log 0.0 MB of 5 MB\nWARN authored PR discovery failed: gh did not return arrays of pages\n" {
		t.Fatalf("printed %q", got)
	}
}

// The retry row runs its own step dry: it says what it would retry and sends nothing. What the
// rows say waits until every row and GitHub pass are Go's, so a later event Go cannot read, or a
// pull request of this account's on another's repository that merged, prints none of it.
func TestDryTickReportsRetriesButBuffersTheWholePreview(t *testing.T) {
	ak, gh := idleHome(t, "echo 'To get started, please run:\n\n  gh auth login' >&2; exit 4")
	put(t, filepath.Join(ak, "state", "notification-outbox", "card.json"), run.Line(run.Fields("id", "card", "source", "card:done-1",
		"episode", "done-1", "session", "acme", "kind", "done", "created_at", epoch(time.Now()), "status", "pending")))
	before := files(t, filepath.Dir(ak))
	var out bytes.Buffer
	if !Dry(&out) || out.String() != "lock free · no tick has ended yet · watch.log 0.0 MB of 5 MB\n"+
		"would retry notification card (pending)\ngh is not logged in; PR checks skipped (To get started, please run: gh auth login)\n" {
		t.Fatalf("printed %q", &out)
	}
	if after := files(t, filepath.Dir(ak)); !reflect.DeepEqual(after, before) {
		t.Fatal("the dry tick changed HOME")
	}
	unread := filepath.Join(ak, "state", "notification-outbox", "zz.json")
	put(t, unread, "")
	if out.Reset(); Dry(&out) || out.Len() > 0 {
		t.Fatalf("a later unreadable event printed %q", &out)
	}
	if err := os.Remove(unread); err != nil {
		t.Fatal(err)
	}
	gh(`[ "$*" = "api user" ] && exec echo '{"login": "acme"}'
case "$*" in *"pr view"*) exec echo '{"state": "MERGED"}' ;; esac
echo '{"items": [{"pull_request": {"html_url": "https://github.com/other/app/pull/1"}}]}'`)
	if Dry(&out) || out.Len() > 0 {
		t.Fatalf("a merged pull request printed %q", &out)
	}
}

// The seat health row runs its own step dry: of a seat stopped with its plan open, the dry tick
// says the `continue` the real one would type, and types, keeps and locks nothing.
func TestDryTickSaysItWouldContinueAnOpenPlan(t *testing.T) {
	ak, _ := idleHome(t, loggedOut)
	home := filepath.Dir(ak)
	put(t, filepath.Join(ak, "config.toml"), "[audit]\non = false\n[models.opus]\nharness='claude'\nmodel='claude-opus'\neffort='xhigh'\nprovider='test'\n[providers.test]\nmode='subscription'\n")
	put(t, filepath.Join(ak, "state", "session-acme.json"), run.Line(run.Fields("orchestrator", "opus", "workers", []any{"opus"},
		"cwd", filepath.Join(home, "work", "acme"), "created", 1799000000, "conversation", "conv-acme", "id_source", "launcher", "resumable", true, "session_title", "acme")))
	put(t, filepath.Join(ak, "state", "plan-acme.md"), openPlan)
	drawn(t, home, "The patch is ready.\n────────\n❯\n────────\n  ⏵⏵ bypass permissions on (shift+tab to cycle)\n")
	before := files(t, home)
	var out bytes.Buffer
	if !Dry(&out) || out.String() != continued {
		t.Fatalf("printed %q", &out)
	}
	if after := files(t, home); !reflect.DeepEqual(after, before) {
		t.Fatal("the dry tick changed HOME")
	}
}

// A dry tick follows a Muse seat's launch through Muse's `/new` as every read does, and decides
// on the session it moved to, keeping nothing of it: its receipt reads as it was, as does all of
// HOME, where any other read keeps that session, for the seat to reopen on once that Muse is gone.
func TestDryDiscoveryLeavesAMuseReceiptAsItWas(t *testing.T) {
	if runtime.GOOS != "linux" {
		t.Skip("a process's birth is read off Linux's /proc")
	}
	ak, _ := idleHome(t, loggedOut)
	home := filepath.Dir(ak)
	t.Setenv("XDG_DATA_HOME", filepath.Join(home, "data"))
	put(t, filepath.Join(ak, "config.toml"), "[audit]\non = false\n[models.spark]\nharness='muse'\nmodel='spark'\neffort='high'\nprovider='test'\n[providers.test]\nmode='subscription'\n")
	token := strings.Repeat("a", 32)
	put(t, filepath.Join(ak, "state", "session-acme.json"), run.Line(run.Fields("orchestrator", "spark", "workers", []any{"spark"},
		"cwd", filepath.Join(home, "work", "acme"), "created", 1799000000, "muse_launch", token, "resumable", true, "session_title", "acme")))
	put(t, filepath.Join(ak, "state", "plan-acme.md"), openPlan)
	// the launch's Muse is this process, which the registry has moved to the session after `/new`
	birth, born := host.ReadIdentity(os.Getpid())
	if !born {
		t.Fatal("this process has no birth")
	}
	receipt := filepath.Join(ak, "state", "muse-launch-"+token)
	put(t, filepath.Join(receipt, "session"), "opened")
	put(t, filepath.Join(receipt, "lineage"), run.Line(run.Fields("processes", []any{[]any{run.Number(fmt.Sprint(os.Getpid())),
		run.Fields("boot", birth.Boot, "ticks", int(birth.Ticks), "started_at", birth.StartedAt)}}, "earlier", []any{})))
	put(t, filepath.Join(home, "data", "muse", "runtime", "muse", "sessions", "after-new.json"),
		run.Line(run.Fields("session_id", "after-new", "process_generation_hint", fmt.Sprintf("pid=%d", os.Getpid()))))
	drawn(t, home, "The patch is ready.\n────────\n❯\n────────\nspark · high · acme · YOLO\n")
	before := files(t, home)
	var out bytes.Buffer
	if !Dry(&out) || out.String() != continued {
		t.Fatalf("printed %q", &out)
	}
	if after := files(t, home); !reflect.DeepEqual(after, before) {
		t.Fatal("the dry tick changed HOME")
	}
	if owned, known := harness.Owned("muse", map[string]any{"muse_launch": token}); owned != "after-new" || !known {
		t.Fatalf("followed to %q (%v)", owned, known)
	}
	if kept := read(t, filepath.Join(receipt, "session")); kept != "after-new" {
		t.Fatalf("a read after the dry tick kept %q", kept)
	}
}

// loggedOut is a gh logged in as nobody, openPlan a plan with work open, and continued what a dry
// tick says of a seat stopped there.
const (
	loggedOut = "echo 'To get started, please run:\n\n  gh auth login' >&2; exit 4"
	openPlan  = "- [ ] Ship it · check: `true` · acme · written 2026-10-23 09:00\n"
	continued = "lock free · no tick has ended yet · watch.log 0.0 MB of 5 MB\n" +
		"would resume acme, stopped with work open, no question and no run, with 'continue'\n" +
		"gh is not logged in; PR checks skipped (To get started, please run: gh auth login)\n"
)

// drawn opens the seat acme on a pane of ak's own drawing screen, once it shows.
func drawn(t *testing.T, home, screen string) {
	t.Helper()
	if _, err := exec.LookPath("tmux"); err != nil {
		t.Skip("no tmux installed")
	}
	path := filepath.Join(home, "screen")
	put(t, path, screen)
	t.Cleanup(func() { tmux.Ask(tmux.Own(), "kill-server") })
	if err := tmux.Spawn(tmux.Own(), os.Getenv("PATH"), "new-session", "-d", "-s", "acme", "-x", "80", "-y", "24", "sh", "-c", "cat "+path+"; read _"); err != nil {
		t.Fatal(err)
	}
	pane, err := tmux.Ask(tmux.Own(), "display-message", "-p", "-t", "=acme:", "#{pane_id}")
	if err != nil {
		t.Fatal(err)
	}
	tmux.Ask(tmux.Own(), "set-option", "-t", "=acme:", tmux.Mark, "1")
	tmux.Ask(tmux.Own(), "set-option", "-t", "=acme:", tmux.HarnessPane, pane)
	for deadline := time.Now().Add(10 * time.Second); ; time.Sleep(10 * time.Millisecond) {
		if shown, _ := tmux.Ask(tmux.Own(), "capture-pane", "-p", "-t", pane); bytes.Contains([]byte(shown), []byte("The patch is ready.")) {
			break
		} else if time.Now().After(deadline) {
			t.Fatalf("never drew the screen: %q", shown)
		}
	}
}
