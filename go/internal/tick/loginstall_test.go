//go:build unix

package tick

import (
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// Every seat on a harness whose seat login its verb refused keeps a stall, notice and page of its
// own, the one on its logout words and the one at its prompt alike, each begun when that login's
// no was, which stands while the verb keeps saying it (watch.record_auth, watch.logged_out).
func TestEverySeatOnARefusedLoginKeepsItsOwnStallFromTheLoginsOneBeginning(t *testing.T) {
	ak, _ := idleHome(t, answers)
	put(t, filepath.Join(ak, "config.toml"), "[audit]\non = false\n[models.opus]\nharness='claude'\nmodel='claude-opus'\neffort='xhigh'\nprovider='test'\n[providers.test]\nmode='subscription'\n")
	adapters := t.TempDir()
	t.Setenv("AGENTKIT_ADAPTER_DIR", adapters)
	put(t, filepath.Join(adapters, "claude.sh"), "#!/bin/sh\n[ \"$*\" = 'auth seat' ] || exit 3\necho 'token expired'; exit 1\n")
	if err := os.Chmod(filepath.Join(adapters, "claude.sh"), 0o700); err != nil {
		t.Fatal(err)
	}
	tick := checking(t, io.Discard)
	for _, each := range []struct {
		name  string
		login any
	}{{"acme", "Please run /login"}, {"beta", nil}} {
		live := seat.Live{Name: each.name, Own: "claude", Login: each.login, Pane: "❯", Bound: true, File: run.NewObject(),
			Record: run.Fields("orchestrator", "opus", "session_title", each.name)}
		answer, decided := tick.loginOut(live)
		if !decided || answer == nil {
			t.Fatalf("%s: login out decided %v, answer %v", each.name, decided, answer)
		}
		if carried, err := tick.keepLogin(live, answer); !carried || err != nil {
			t.Fatalf("%s: kept %v, %v", each.name, carried, err)
		}
	}
	numbered := func(name string) map[string]any {
		decoder := json.NewDecoder(strings.NewReader(read(t, filepath.Join(ak, "state", name))))
		decoder.UseNumber()
		var found map[string]any
		if err := decoder.Decode(&found); err != nil {
			t.Fatal(err)
		}
		return found
	}
	state := numbered("watch.json")
	at := state["auth_out"].(map[string]any)["claude"].(map[string]any)["at"]
	for _, name := range []string{"acme", "beta"} {
		stall := state["stalls"].(map[string]any)[name].(map[string]any)
		notice := numbered("notify-" + name + ".json")
		if stall["kind"] != "auth" || stall["since"] != at || stall["told"] == nil || notice["source"] != "auth:"+name+":claude:"+string(at.(json.Number)) {
			t.Errorf("%s: stall %v, notice %v, the login's at %v", name, stall, notice, at)
		}
	}
}
