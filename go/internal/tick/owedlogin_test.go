//go:build unix

package tick

import (
	"errors"
	"io"
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// A seat whose own login is not out but a run of its own waits on one keeps a stall of kind
// `auth` whose evidence is that run, dated from when it parked, its signature what the run said
// where the screen shows no logout words, and pages its owner once; nothing asks that login's
// verb, and no answer of one goes on record.  A dry tick keeps none and leaves it to Python
// (watch.health).
func TestARunWaitingOnALoginKeepsItsSeatsStallAndPagesOnce(t *testing.T) {
	ak, _ := idleHome(t, answers)
	put(t, filepath.Join(ak, "config.toml"), "[audit]\non = false\n[models.opus]\nharness='claude'\nmodel='claude-opus'\neffort='xhigh'\nprovider='test'\n[providers.test]\nmode='subscription'\n")
	asks := loginAsks(t)
	live := seat.Live{Name: "acme", Own: "claude", Pane: "❯", Bound: true, File: run.NewObject(), Record: run.Fields("orchestrator", "opus", "session_title", "acme"),
		Owed: &seat.Owed{Login: "claude", Since: run.Number("20"), Why: "claude login expired"}}
	dry := checking(t, io.Discard)
	dry.dry = true
	if dry.keepsLogin(live) {
		t.Fatal("a dry tick keeps the stall")
	}
	tick := checking(t, io.Discard)
	if answer, decided := tick.loginOut(live); decided || answer != nil || !tick.keepsLogin(live) {
		t.Fatalf("its own login decided %v, %v", decided, answer)
	}
	if carried, err := tick.keepLogin(live, nil); !carried || err != nil {
		t.Fatalf("kept %v, %v", carried, err)
	}
	state := checking(t, io.Discard).state
	stall := state.Dict("stalls").Dict("acme")
	notice, _ := run.ReadJSON(filepath.Join(ak, "state", "notify-acme.json"))
	if stall.Get("kind") != "auth" || stall.Get("evidence") != "run" || stall.Get("harness") != "claude" || stall.Get("since") != run.Number("20") ||
		stall.Get("signature") != "claude login expired" || !stall.Truthy("told") || notice.Get("source") != "auth:acme:claude:20" || notice.Get("kind") != "needs" {
		t.Errorf("watch.json holds %s, the notice %s", read(t, filepath.Join(ak, "state", "watch.json")), run.Line(notice))
	}
	if state.Has("auth_out") || read(t, asks) != "" {
		t.Errorf("asked %q, on record %s", read(t, asks), run.Line(state.Get("auth_out")))
	}
	if checking(t, io.Discard).keepsLogin(live) {
		t.Error("paged again over its standing notice")
	}
}

// A login stall that stands because a run of the seat's own waits on its login takes that run as
// its evidence, and its error as its signature, written before the seat's word reads it; once no
// run owes the login, whatever that login's verb says, its stall goes and its notice is seen.  A run
// waiting on another login than the stall's is Python's, to begin that login's stall (watch.health,
// forget).
func TestALoginStallARunWaitsOnFollowsTheRunAndClearsWhenItEnds(t *testing.T) {
	for _, each := range []struct{ stall, owed string }{{"claude", "claude"}, {"codex", "codex"}, {"claude", "codex"}} {
		t.Run(each.stall+" stall, "+each.owed+" owed", func(t *testing.T) {
			ak, _ := idleHome(t, answers)
			home := filepath.Dir(ak)
			put(t, filepath.Join(ak, "config.toml"), "[audit]\non = false\n[models.opus]\nharness='claude'\nmodel='claude-opus'\neffort='xhigh'\nprovider='test'\n[providers.test]\nmode='subscription'\n")
			put(t, filepath.Join(ak, "state", "session-acme.json"), run.Line(run.Fields("orchestrator", "opus", "workers", []any{"opus"},
				"cwd", filepath.Join(home, "work", "acme"), "created", 1799000000, "conversation", "conv-acme", "id_source", "launcher",
				"resumable", true, "session_title", "acme")))
			drawn(t, home, "The patch is ready.\n────────\n❯\n────────\n")
			loginAsks(t)
			codex := filepath.Join(os.Getenv("AGENTKIT_ADAPTER_DIR"), "codex.sh")
			put(t, codex, "#!/bin/sh\necho 'token expired'; exit 1\n")
			if err := os.Chmod(codex, 0o700); err != nil {
				t.Fatal(err)
			}
			path, notice, watch := filepath.Join(ak, "runs", "fix-api", "run.json"), filepath.Join(ak, "state", "notify-acme.json"), filepath.Join(ak, "state", "watch.json")
			put(t, path, `{"state":"waiting_login","waiting_for":"`+each.owed+`","launched_session":"acme","finished_at":20,"error":"the run's error"}`)
			put(t, watch, `{"auth_out":{"codex":{"ok":false,"why":"token expired","at":10}},"stalls":{"acme":{"kind":"auth","harness":"`+each.stall+`","since":10,`+
				`"evidence":"verb","signature":"token expired","notice":"needs login","told":11}}}`)
			put(t, notice, `{"session":"acme","kind":"needs","text":"needs login","source":"auth:acme:`+each.stall+`:10","watcher":true,"time":11}`)
			before := read(t, watch)
			err := checking(t, io.Discard).health()
			if each.stall != each.owed {
				if !errors.Is(err, errLeft) || read(t, watch) != before {
					t.Fatalf("carried %v, watch.json %s", err, read(t, watch))
				}
				return
			}
			stall := checking(t, io.Discard).state.Dict("stalls").Dict("acme")
			if err != nil || stall.Get("evidence") != "run" || stall.Get("signature") != "the run's error" || stall.Get("since") != run.Number("10") || !stall.Truthy("told") {
				t.Fatalf("%v, the stall %s", err, run.Line(stall))
			}
			put(t, path, `{"state":"pass","launched_session":"acme","finished_at":30,"handed_back":true}`)
			said, _ := run.ReadJSON(notice)
			if err := checking(t, io.Discard).health(); err != nil || said.Truthy("seen") {
				t.Fatalf("%v, seen before %s", err, run.Line(said))
			}
			said, _ = run.ReadJSON(notice)
			if checking(t, io.Discard).state.Dict("stalls").Has("acme") || said.Get("seen") != true {
				t.Errorf("no run owes %s, but watch.json holds %s, the notice %s", each.owed, read(t, watch), run.Line(said))
			}
		})
	}
}

// loginAsks is the file a claude adapter that says its seat login is in place adds a line to each
// time it is asked.
func loginAsks(t *testing.T) string {
	t.Helper()
	adapters := t.TempDir()
	t.Setenv("AGENTKIT_ADAPTER_DIR", adapters)
	asks := filepath.Join(adapters, "asks")
	put(t, asks, "")
	put(t, filepath.Join(adapters, "claude.sh"), "#!/bin/sh\n[ \"$*\" = 'auth seat' ] || exit 3\necho >>'"+asks+"'\necho 'token in place'\n")
	if err := os.Chmod(filepath.Join(adapters, "claude.sh"), 0o700); err != nil {
		t.Fatal(err)
	}
	return asks
}
