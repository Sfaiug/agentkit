//go:build unix

package tick

import (
	"bytes"
	"os"
	"path/filepath"
	"reflect"
	"testing"
	"time"

	"agentkit/internal/run"
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
