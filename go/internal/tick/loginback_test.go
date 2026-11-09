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
