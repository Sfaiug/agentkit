package cli

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"agentkit/internal/config"
	"agentkit/internal/seat"
)

const offRefusal = "five is off in the model list"

// offHome is a home whose one model, five, runs a release the stored lineup rates and
// `models_off` turns off; its harness's adapter answers every verb, so only the list refuses.
func offHome(t *testing.T, provider string) string {
	t.Helper()
	home := sandbox(t)
	t.Setenv("AGENTKIT_SESSION", "")
	t.Setenv("AGENTKIT_TMUX_SOCKET", "acme-off")
	t.Setenv("TMUX", "")
	bin := filepath.Join(home, "fake")
	write(t, filepath.Join(bin, "tmux"), "#!/bin/sh\nexit 1\n")
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
	adapters := filepath.Join(home, "adapters")
	t.Setenv("AGENTKIT_ADAPTER_DIR", adapters)
	manifest, err := os.ReadFile(filepath.Join("..", "..", "..", "adapters", "codex.toml"))
	if err != nil {
		t.Fatal(err)
	}
	write(t, filepath.Join(adapters, "codex.toml"), string(manifest))
	write(t, filepath.Join(adapters, "codex.sh"), "#!/bin/sh\ncase \"$1\" in\nusage) echo '{\"meters\":[]}' ;;\ninteractive) echo /bin/true ;;\nesac\n")
	for _, script := range []string{filepath.Join(bin, "tmux"), filepath.Join(adapters, "codex.sh")} {
		if err := os.Chmod(script, 0o700); err != nil {
			t.Fatal(err)
		}
	}
	write(t, filepath.Join(home, ".agentkit", "config.toml"), "companies=['Acme']\nmodels_off=['acme-5']\n[defaults]\n"+
		"orchestrator='five'\nworkers=['five']\n[models.five]\nharness='codex'\nmodel='acme-5'\neffort='high'\nprovider='test'\n"+
		"[providers.test]\nmode='subscription'\n"+provider)
	write(t, filepath.Join(home, ".agentkit", "state", "matrix.json"), `{"matrix":{"lineup":[{"release":"acme-5","maker":"Acme",`+
		`"effort":"high","values":{"aa.intelligenceIndex":50,"arena.agent":0.6,"aa.frontierCode20":0.6,"aa.omniscience":50},`+
		`"yours":[{"harness":"codex","model":"acme-5"}]}]}}`)
	return home
}

// A saved seat on a model off in the model list comes back on none, a preview's included, and a
// menu's new seat opens on none: each refused in Python's words before anything is written.
func TestNoSeatComesBackOrOpensOnAModelOff(t *testing.T) {
	for _, conversation := range []string{"", "conv-acme"} {
		for _, dry := range []bool{true, false} {
			t.Run(conversation+map[bool]string{true: " dry"}[dry], func(t *testing.T) {
				home := offHome(t, "")
				record := map[string]any{"orchestrator": "five", "workers": []string{"five"}, "cwd": home}
				if conversation != "" {
					record["conversation"], record["id_source"] = conversation, "launcher"
				}
				saved, _ := json.Marshal(record)
				write(t, filepath.Join(home, ".agentkit", "state", "session-acme.json"), string(saved))
				before := tree(t, home)
				args := []string{"orch", "acme"}
				if dry {
					args = append(args, "--dry-run")
				}
				var out, errOut bytes.Buffer
				if code := Main(args, &out, &errOut); code != 2 || !strings.Contains(errOut.String(), offRefusal) {
					t.Errorf("exit %d, said %q", code, out.String()+errOut.String())
				}
				if after := tree(t, home); !reflect.DeepEqual(before, after) {
					t.Errorf("wrote before refusing: %v", after)
				}
			})
		}
	}
	home := offHome(t, "accounts=['default']\n")
	models, err := config.Models()
	if err != nil {
		t.Fatal(err)
	}
	before := tree(t, home)
	if known, err := seat.Open("fix-api", "five", models, []string{"five"}, home, false); !known || err == nil || !strings.Contains(err.Error(), offRefusal) {
		t.Errorf("opened %v: %v", known, err)
	}
	if after := tree(t, home); !reflect.DeepEqual(before, after) {
		t.Errorf("wrote before refusing: %v", after)
	}
}
