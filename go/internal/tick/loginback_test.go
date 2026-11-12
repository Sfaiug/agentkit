//go:build unix

package tick

import (
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
	"agentkit/internal/seat"
	"agentkit/internal/tmux"
)

// A login a seat holds a stall of is asked once a pass, whether it is on record as refused, as
// passing, or not at all, and once it passes the seat's stall of it goes and its notice is seen,
// its alert generation moved on; a dry tick asks too, but drops the stall only from what it reads
// (watch.health, watch.forget).
func TestALoginThatPassesAgainClearsItsStallAndNotice(t *testing.T) {
	for _, record := range []string{`, "auth_out": {"claude": {"ok": false, "why": "token expired", "at": 1}}`, `, "auth_out": {"claude": {"ok": true, "why": "token in place", "at": 1}}`, ""} {
		for _, dry := range []bool{false, true} {
			ak, _ := idleHome(t, answers)
			put(t, filepath.Join(ak, "config.toml"), "[audit]\non = false\n[models.opus]\nharness='claude'\nmodel='claude-opus'\neffort='xhigh'\nprovider='test'\n[providers.test]\nmode='subscription'\n")
			adapters := t.TempDir()
			t.Setenv("AGENTKIT_ADAPTER_DIR", adapters)
			asks := filepath.Join(adapters, "asks")
			put(t, filepath.Join(adapters, "claude.sh"), "#!/bin/sh\n[ \"$*\" = 'auth seat' ] || exit 3\necho >>'"+asks+"'\necho 'token in place'\n")
			if err := os.Chmod(filepath.Join(adapters, "claude.sh"), 0o700); err != nil {
				t.Fatal(err)
			}
			const text = "acme (Claude) needs login: open the host, press this session's number, and log in again."
			watch, notice := filepath.Join(ak, "state", "watch.json"), filepath.Join(ak, "state", "notify-acme.json")
			put(t, watch, `{"stalls": {"acme": {"kind": "auth", "harness": "claude", "since": 1, "evidence": "verb", "signature": "token expired", `+
				`"pane": "❯", "notice": "`+text+`", "told": 2}}`+record+`}`)
			put(t, notice, `{"session": "acme", "kind": "needs", "text": "`+text+`", "source": "auth:acme:claude:1", "watcher": true, "time": 2}`)
			before, asked := read(t, watch), read(t, notice)
			tick := checking(t, io.Discard)
			tick.dry = dry
			if err := tick.askLogins(); err != nil {
				t.Fatalf("%s, dry %v: %v", record, dry, err)
			}
			live := seat.Live{Name: "acme", Own: "claude", Pane: "❯", Bound: true, File: run.NewObject(), Record: run.Fields("orchestrator", "opus", "session_title", "acme")}
			held := tick.state.Dict("stalls").Dict("acme")
			if stands, back, _ := tick.loginHeld(live, held); stands || !back || !tick.loggedIn("claude") || read(t, asks) != "\n" {
				t.Fatalf("%s, dry %v: the stall stands %v, its login back %v, asked %q, the tick's logins %v", record, dry, stands, back, read(t, asks), run.Line(tick.state.Get("auth_out")))
			}
			if carried, err := tick.clearLogin(live, held); !carried || err != nil || tick.state.Dict("stalls").Has("acme") {
				t.Fatalf("%s, dry %v: cleared %v, %v, the tick's stalls %v", record, dry, carried, err, run.Line(tick.state.Get("stalls")))
			}
			kept, said := checking(t, io.Discard).state, read(t, notice)
			if dry {
				if read(t, watch) != before || said != asked {
					t.Errorf("a dry tick wrote %s and %s", read(t, watch), said)
				}
				continue
			}
			seen, _ := run.Num(kept.Dict("seen_at").Get("acme"))
			notified, _ := run.ReadJSON(notice)
			if kept.Dict("stalls").Has("acme") || seen <= 2 || notified.Get("seen") != true || record != "" && kept.Dict("auth_out").Dict("claude").Get("ok") != true {
				t.Errorf("%s: watch.json holds %s, the notice %s", record, read(t, watch), said)
			}
		}
	}
}

// A seat whose panes all die while its refused login is asked again, the login now passing, is no
// seat Go clears that login's stall at: Python's look still reads the login of a seat tmux holds
// dead, so the health row hands the tick over at it, its stall and notice standing, a dry tick alike.
func TestALoginStallAtASeatThatDiesWhileItsLoginIsAskedIsPythons(t *testing.T) {
	for _, dry := range []bool{false, true} {
		t.Run(fmt.Sprint("dry ", dry), func(t *testing.T) {
			ak, _ := idleHome(t, answers)
			home := filepath.Dir(ak)
			put(t, filepath.Join(ak, "config.toml"), "[audit]\non = false\n[models.opus]\nharness='claude'\nmodel='claude-opus'\neffort='xhigh'\nprovider='test'\n[providers.test]\nmode='subscription'\n")
			put(t, filepath.Join(ak, "state", "session-acme.json"), run.Line(run.Fields("orchestrator", "opus", "workers", []any{"opus"},
				"cwd", filepath.Join(home, "work", "acme"), "created", 1799000000, "conversation", "conv-acme", "id_source", "launcher",
				"resumable", true, "session_title", "acme")))
			watch, notice := filepath.Join(ak, "state", "watch.json"), filepath.Join(ak, "state", "notify-acme.json")
			put(t, watch, `{"stalls": {"acme": {"kind": "auth", "harness": "claude", "evidence": "verb", "since": 1, "told": 2, "notice": "needs login"}}, `+
				`"auth_out": {"claude": {"ok": false, "why": "expired", "at": 1}}}`)
			put(t, notice, `{"session": "acme", "kind": "needs", "text": "needs login", "watcher": true, "time": 2}`)
			drawn(t, home, "The patch is ready.\n────────\n❯\n────────\n")
			if _, err := tmux.Ask(tmux.Own(), "set-option", "-t", "=acme:", "remain-on-exit", "on"); err != nil {
				t.Fatal(err)
			}
			pid, err := tmux.Ask(tmux.Own(), "display-message", "-p", "-t", "=acme:", "#{pane_pid}")
			if err != nil {
				t.Fatal(err)
			}
			adapters := t.TempDir()
			t.Setenv("AGENTKIT_ADAPTER_DIR", adapters)
			// the seat's pane dies while its login is asked, which then passes
			put(t, filepath.Join(adapters, "claude.sh"), "#!/bin/sh\n[ \"$*\" = 'auth seat' ] || exit 3\nkill -TERM "+pid+"\n"+
				"for _ in 1 2 3 4 5 6 7 8 9 10; do\n"+
				"  [ \"$(tmux -L tick-test display-message -p -t =acme: '#{pane_dead}')\" = 1 ] && echo 'token in place' && exit 0\n"+
				"  sleep .05\ndone\nexit 3\n")
			if err := os.Chmod(filepath.Join(adapters, "claude.sh"), 0o700); err != nil {
				t.Fatal(err)
			}
			tick := checking(t, io.Discard)
			tick.dry = dry
			if err := tick.health(); !errors.Is(err, errLeft) || !tick.loggedIn("claude") {
				t.Fatalf("the health row ended %v, the login passing %v", err, tick.loggedIn("claude"))
			}
			if said, _ := run.ReadJSON(notice); !checking(t, io.Discard).state.Dict("stalls").Has("acme") || said.Truthy("seen") {
				t.Errorf("handed over with watch.json %s, the notice %s", read(t, watch), read(t, notice))
			}
		})
	}
}
