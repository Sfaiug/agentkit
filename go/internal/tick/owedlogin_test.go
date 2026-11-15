//go:build unix

package tick

import (
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

// The stall a run of the seat's own raised stands while one of its runs waits on that login, and
// once none does it is over, whatever that login's verb says: its stall goes and its notice is
// seen.  A run waiting on another login is Python's to begin a stall of (watch.health, forget).
func TestARunsLoginStallStandsWhileARunWaitsOnIt(t *testing.T) {
	ak, _ := idleHome(t, answers)
	put(t, filepath.Join(ak, "config.toml"), "[audit]\non = false\n[models.opus]\nharness='claude'\nmodel='claude-opus'\neffort='xhigh'\nprovider='test'\n[providers.test]\nmode='subscription'\n")
	loginAsks(t)
	const text = "acme (Claude) needs login: open the host, press this session's number, and log in again."
	notice := filepath.Join(ak, "state", "notify-acme.json")
	put(t, filepath.Join(ak, "state", "watch.json"), `{"stalls": {"acme": {"kind": "auth", "harness": "claude", "since": 20, "evidence": "run", "signature": "claude login expired", `+
		`"pane": "❯", "notice": "`+text+`", "told": 21}}}`)
	put(t, notice, `{"session": "acme", "kind": "needs", "text": "`+text+`", "source": "auth:acme:claude:20", "watcher": true, "time": 21}`)
	live := seat.Live{Name: "acme", Own: "claude", Pane: "❯", Bound: true, File: run.NewObject(), Record: run.Fields("orchestrator", "opus", "session_title", "acme")}
	tick := checking(t, io.Discard)
	held := tick.state.Dict("stalls").Dict("acme")
	for login, stands := range map[string]bool{"claude": true, "shop": false} {
		owing := live
		owing.Owed = &seat.Owed{Login: login, Since: run.Number("20")}
		if standing, back, _ := tick.loginHeld(owing, held); standing != stands || back {
			t.Errorf("a run waiting on %s: the stall stands %v, its login back %v", login, standing, back)
		}
	}
	if stands, back, _ := tick.loginHeld(live, held); stands || !back {
		t.Fatalf("no run waiting: the stall stands %v, its login back %v", stands, back)
	}
	if carried, err := tick.clearLogin(live, held); !carried || err != nil {
		t.Fatalf("cleared %v, %v", carried, err)
	}
	said, _ := run.ReadJSON(notice)
	if checking(t, io.Discard).state.Dict("stalls").Has("acme") || said.Get("seen") != true {
		t.Errorf("watch.json holds %s, the notice %s", read(t, filepath.Join(ak, "state", "watch.json")), run.Line(said))
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
