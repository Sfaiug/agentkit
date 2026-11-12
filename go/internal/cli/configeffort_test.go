package cli

import (
	"bytes"
	"os"
	"path/filepath"
	"runtime"
	"testing"

	"agentkit/internal/matrix"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

func TestConfigStepsOnlyAdapterEffortsOncePerScreenAndHandsOffRestarts(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("the fake adapter is a shell script")
	}
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	adapters := filepath.Join(home, "adapters")
	t.Setenv("AGENTKIT_ADAPTER_DIR", adapters)
	put := func(path, text string) {
		t.Helper()
		if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(text), 0o700); err != nil {
			t.Fatal(err)
		}
	}
	path := filepath.Join(home, ".agentkit", "config.toml")
	put(path, "[models.one]\nharness='acme'\nmodel='m1'\neffort='high'\nprovider='fuel'\n[providers.fuel]\nmode='subscription'\n")
	put(filepath.Join(adapters, "acme.toml"), "[effort]\nlevels=['low','medium','high','max']\n")
	script := filepath.Join(adapters, "acme.sh")
	put(script, "#!/bin/sh\nprintf 'm1\tModel One\tlow high\n'\n")
	record := filepath.Join(home, ".agentkit", "state", "session-acme.json")
	put(record, "{  \"orchestrator\":\"one\",\"workers\":[\"one\"],\"conversation\":\"first\" }\n")
	c, err := matrix.Configured()
	if err != nil {
		t.Fatal(err)
	}
	catalogs := configCatalog{}
	if err := catalogs.read(c); err != nil {
		t.Fatal(err)
	}
	// The catalog changes after it was read, and another writer changes the record before Space.
	put(script, "#!/bin/sh\nexit 19\n")
	if err := catalogs.read(c); err != nil {
		t.Fatal(err)
	}
	put(record, `{"orchestrator":"one","workers":["one"],"reviewers":["one"],"conversation":"second","custom":17,"efforts":{"one":{"effort":"high","review_effort":"medium"}}}`)
	configBefore, _ := os.ReadFile(path)
	for _, word := range []string{"low", "high", "low"} {
		if note, known := stepConfigEffort(c, "acme", 0, 4, -1, unasked(t)); !known || note != "" {
			t.Fatalf("step: %q, %v", note, known)
		}
		saved, err := run.ReadJSON(record)
		if err != nil || saved.Str("conversation") != "second" || saved.Get("custom") != run.Number("17") || saved.Dict("efforts").Dict("one").Str("review_effort") != "medium" || c.Effort("one", 1) != word {
			t.Fatalf("stepped past the adapter or lost record values: %s, %v", run.Line(saved), err)
		}
		if saved.Dict("efforts").Dict("one").Has("exec_effort") != (word != "high") {
			t.Fatal("a build effort at the base effort did not follow it again")
		}
	}
	before, _ := os.ReadFile(record)
	if note, known := stepConfigEffort(c, "acme", 0, 3, -1, unasked(t)); known || note != "" {
		t.Fatalf("restart was not handed off: %q, %v", note, known)
	}
	if after, _ := os.ReadFile(record); !bytes.Equal(after, before) {
		t.Fatal("refused restart rewrote the record")
	}
	if after, _ := os.ReadFile(path); !bytes.Equal(after, configBefore) {
		t.Fatal("effort edit rewrote config.toml")
	}
}

// A step Go does not carry is Python's: onto a model the model list turned off, which Python's
// switch plan refuses before anything else, or into a running harness Go types nothing into.  Go
// writes nothing and owes nothing, the seat's harness running as it does.
func TestAStepGoDoesNotCarryIsHandedOff(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("the fakes are shell scripts")
	}
	for name, config := range map[string]string{
		"a model turned off":              "companies = ['Acme']\nmodels_off = ['acme-mid-5']\n[models.mid]\nharness = 'claude'\n",
		"a harness Go types nothing into": "[models.mid]\nharness = 'acme'\n",
	} {
		t.Run(name, func(t *testing.T) {
			home := t.TempDir()
			for key, value := range map[string]string{"HOME": home, "USERPROFILE": home, "AGENTKIT_TMUX_SOCKET": "effort-handoff",
				"AGENTKIT_SESSION": "acme", "AGENTKIT_ACCOUNT": "", "AGENTKIT_ADAPTER_DIR": filepath.Join(home, "adapters"),
				"PATH": filepath.Join(home, "bin") + string(os.PathListSeparator) + os.Getenv("PATH")} {
				t.Setenv(key, value)
			}
			put := func(path, text string) {
				t.Helper()
				if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(path, []byte(text), 0o700); err != nil {
					t.Fatal(err)
				}
			}
			put(filepath.Join(home, ".agentkit", "config.toml"), config+
				"model = 'acme-mid-5'\neffort = 'high'\nprovider = 'fuel'\n[providers.fuel]\nmode = 'subscription'\n")
			put(filepath.Join(home, ".agentkit", "state", "matrix.json"), `{"matrix": {"lineup": [{"release": "acme-mid-5", "maker": "Acme", "effort": "high", `+
				`"values": {"aa.intelligenceIndex": 50, "arena.agent": 0.6, "aa.frontierCode20": 0.6, "aa.omniscience": 50}, "yours": [{"harness": "claude", "model": "acme-mid-5"}]}]}}`)
			for _, harness := range []string{"claude", "acme"} {
				put(filepath.Join(home, "adapters", harness+".sh"), "#!/bin/sh\nprintf 'signed in\\n'\n")
			}
			// a harness switched in place whose screen nobody reads
			put(filepath.Join(home, "adapters", "acme.toml"), "version = 1\nname = 'Acme'\n[switch]\nmodel = '/model {model}'\n[screen]\ncomposer = '('\n")
			for _, program := range []string{"claude", "acme"} {
				put(filepath.Join(home, "bin", program), "#!/bin/sh\nexit 0\n")
			}
			put(filepath.Join(home, "bin", "tmux"), `#!/bin/sh
case "$*" in
  *list-sessions*) printf 'acme\t1\n' ;;
  *list-panes*) printf 'acme\t0\n' ;;
  *show-options*) printf '%%1\n' ;;
  *'#{session_name}'*) echo acme ;;
  *'#{pane_dead}'*) echo 0 ;;
esac
`)
			record := filepath.Join(home, ".agentkit", "state", "session-acme.json")
			put(record, `{"orchestrator": "mid", "workers": ["mid"], "efforts": {"mid": {"effort": "high"}}}`)
			c, err := matrix.Configured()
			if err != nil {
				t.Fatal(err)
			}
			if c.Selected, err = seat.ConfigSelection("acme"); err != nil || c.Selected == nil {
				t.Fatal("the seat's selection cannot be read", err)
			}
			c.Levels["mid"] = []string{"high", "max"}
			before, _ := os.ReadFile(record)
			if note, known := stepConfigEffort(c, "acme", 0, 3, -1, unasked(t)); known || note != "" {
				t.Fatalf("the step was not handed off: %q, %v", note, known)
			}
			if after, _ := os.ReadFile(record); !bytes.Equal(after, before) {
				t.Fatalf("a step handed off rewrote the record: %s", after)
			}
			if _, err := os.Stat(filepath.Join(home, ".agentkit", "state", "seat-acme.json")); !os.IsNotExist(err) {
				t.Fatal("a step handed off owes the seat a line", err)
			}
		})
	}
}

// unasked is a card no step may ask on: one handed off asks nothing.
func unasked(t *testing.T) seatCard {
	return func(question, _ string, _ bool) (bool, bool) {
		t.Fatalf("asked %q", question)
		return false, false
	}
}
