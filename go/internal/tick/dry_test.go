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
		if (Dry(&out) == "") != want || !want && out.Len() > 0 {
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
// search for this account's pull requests whose item Go cannot read, prints none of it.
func TestDryTickReportsRetriesButBuffersTheWholePreview(t *testing.T) {
	ak, gh := idleHome(t, "echo 'To get started, please run:\n\n  gh auth login' >&2; exit 4")
	put(t, filepath.Join(ak, "state", "notification-outbox", "card.json"), run.Line(run.Fields("id", "card", "source", "card:done-1",
		"episode", "done-1", "session", "acme", "kind", "done", "created_at", epoch(time.Now()), "status", "pending")))
	before := files(t, filepath.Dir(ak))
	var out bytes.Buffer
	if Dry(&out) != "" || out.String() != "lock free · no tick has ended yet · watch.log 0.0 MB of 5 MB\n"+
		"would retry notification card (pending)\ngh is not logged in; PR checks skipped (To get started, please run: gh auth login)\n" {
		t.Fatalf("printed %q", &out)
	}
	if after := files(t, filepath.Dir(ak)); !reflect.DeepEqual(after, before) {
		t.Fatal("the dry tick changed HOME")
	}
	unread := filepath.Join(ak, "state", "notification-outbox", "zz.json")
	put(t, unread, "")
	if out.Reset(); Dry(&out) == "" || out.Len() > 0 {
		t.Fatalf("a later unreadable event printed %q", &out)
	}
	if err := os.Remove(unread); err != nil {
		t.Fatal(err)
	}
	gh(`[ "$*" = "api user" ] && exec echo '{"login": "acme"}'
echo '{"items": [1]}'`)
	if Dry(&out) == "" || out.Len() > 0 {
		t.Fatalf("a search Go cannot read printed %q", &out)
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
	if Dry(&out) != "" || out.String() != continued {
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
	if Dry(&out) != "" || out.String() != continued {
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

// The background work a seat's screen shows is kept by the real look before the account decision
// reads it: on an account running low, the seat stays for that work, and on one spent it moves.
// A dry tick decides the same, carrying the first and handing the second over, and keeps and locks
// none of it, whether a seat file was saved before it or not.
func TestDryScreenHoldsAreNeverSaved(t *testing.T) {
	for _, each := range []struct {
		name, seatFile string
		used           int    // of the seat's own account
		snapshot       string // of usage: fresh, stale or missing
		carried        bool
	}{
		{"carried", "", 97, "fresh", true},
		{"carried, saved", `{"state": "at_prompt", "holds": []}`, 97, "fresh", true},
		{"handed over", "", 100, "fresh", false},
		{"handed over, saved", `{"state": "at_prompt", "holds": []}`, 100, "fresh", false},
		// a snapshot no longer fresh is read as it stands, nothing asked again: one missing decides
		// nothing, and the adapter's answer, every account at 10, would carry a spent one
		{"stale, carried", "", 97, "stale", true},
		{"stale, handed over", "", 100, "stale", false},
		{"missing, handed over", "", 10, "missing", false},
	} {
		t.Run(each.name, func(t *testing.T) {
			ak, _ := idleHome(t, loggedOut)
			home := filepath.Dir(ak)
			adapters := t.TempDir()
			put(t, filepath.Join(adapters, "antigravity.sh"), "#!/bin/sh\n[ \"$1\" = usage ] || exit 1\n"+
				`echo '{"meters": [{"name": "session", "used": 10, "window_secs": 18000, "resets_at": 2000000000}]}'`+"\n")
			if err := os.Chmod(filepath.Join(adapters, "antigravity.sh"), 0o700); err != nil {
				t.Fatal(err)
			}
			t.Setenv("AGENTKIT_ADAPTER_DIR", adapters)
			put(t, filepath.Join(ak, "config.toml"), "[audit]\non = false\n[models.gemini]\nharness='antigravity'\nmodel='gemini'\neffort='high'\nprovider='test'\n"+
				"[providers.test]\nmode='subscription'\naccounts=['default','second']\n")
			put(t, filepath.Join(ak, "state", "session-acme.json"), run.Line(run.Fields("orchestrator", "gemini", "workers", []any{"gemini"},
				"cwd", filepath.Join(home, "work", "acme"), "created", 1799000000, "conversation", "conv-acme", "id_source", "launcher", "resumable", true, "session_title", "acme")))
			if each.seatFile != "" {
				put(t, filepath.Join(ak, "state", "seat-acme.json"), each.seatFile)
			}
			meter := func(used int) *run.Object {
				return run.Fields("meters", []any{run.Fields("name", "session", "used", used, "window_secs", 18000, "resets_at", epoch(time.Now())+3600)})
			}
			if fetched := map[string]float64{"fresh": epoch(time.Now()), "stale": epoch(time.Now()) - 600}; each.snapshot != "missing" {
				put(t, filepath.Join(ak, "state", "usage.json"), run.Line(run.Fields("fetched_at", fetched[each.snapshot],
					"providers", run.Fields("test", run.Fields("accounts", run.Fields("default", meter(each.used), "second", meter(10)))))))
			}
			rule := strings.Repeat("─", 40)
			drawn(t, home, "The patch is ready.\n"+rule+"\n>\n"+rule+"\n● [12:08:46] sleep 45 running\n"+rule+
				"\n? for shortcuts              agentkit (GPT-OSS 120B (Medium))  /agents · 1 task(s) · /tasks\n")
			before := files(t, home)
			var out bytes.Buffer
			if (Dry(&out) == "") != each.carried {
				t.Fatalf("carried %v, printing %q", !each.carried, &out)
			}
			if after := files(t, home); !reflect.DeepEqual(after, before) {
				t.Fatal("the dry tick changed HOME")
			}
		})
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
