//go:build unix

package seat

import (
	"io/fs"
	"maps"
	"os"
	"path/filepath"
	"slices"
	"testing"
)

// A dry look at a seat just reopened, which no look has saved yet, stopped with its plan open, says
// the `continue` the real look would type, and keeps, locks and types nothing; with its plan done
// it says nothing and carries the seat, as the real look types nothing. A harness whose stops the
// tick nudges, with no question to answer or repeat, decides the same.
func TestDryHealthSaysItWouldContinueAnOpenPlan(t *testing.T) {
	for own, screen := range map[string]string{"claude": prompting, "muse": "────────\n❯\n────────\nspark · high · acme · YOLO\n",
		"opencode": "┃\n┃\n┃  Build · vela\n╹\nctrl+p commands\n"} {
		t.Run(own, func(t *testing.T) {
			home := sandbox(t)
			write(t, filepath.Join(home, ".agentkit", "config.toml"), testConfig+"[models.test]\nharness='"+own+"'\nmodel='test'\neffort='high'\nprovider='test'\n")
			record(t, home, "acme", map[string]any{"orchestrator": "test", "workers": []string{"test"}})
			write(t, stateFile(home, "plan-acme.md"), openLine)
			drawn(t, home, "acme", "The patch is ready.\n"+screen)
			dry := func() []string {
				t.Helper()
				var said []string
				before := tree(t, home)
				if carried, err := Health("acme", func(Live) bool { return true }, func(line string) { said = append(said, line) }, true); !carried || err != nil {
					t.Fatal(carried, err)
				}
				if after := tree(t, home); !maps.Equal(after, before) {
					t.Fatalf("the dry look changed HOME: %v", after)
				}
				return said
			}
			if said := dry(); !slices.Equal(said, []string{"would resume acme, stopped with work open, no question and no run, with 'continue'"}) {
				t.Fatalf("said %q", said)
			}
			write(t, stateFile(home, "plan-acme.md"), doneLine)
			if said := dry(); len(said) > 0 {
				t.Fatalf("a done plan said %q", said)
			}
		})
	}
}

// A dry look at a seat whose harness died during its capture carries it, as the real look does,
// and keeps, publishes and locks nothing of it.
func TestDryHealthLeavesADeathDuringCaptureUntouched(t *testing.T) {
	home := diedDuringCapture(t)
	before := tree(t, home)
	carried, err := Health("acme", func(Live) bool {
		t.Fatal("a dead harness reached the live-screen health predicate")
		return false
	}, func(line string) { t.Fatalf("said %q", line) }, true)
	if !carried || err != nil {
		t.Fatal(carried, err)
	}
	if after := tree(t, home); !maps.Equal(after, before) {
		t.Fatalf("the dry look changed HOME: %v", after)
	}
}

// A dry look reads the model its seat's last answer moved to as the real look leaves the record,
// writing no record and taking no lock for it: followed onto a model whose provider lists
// accounts, the seat is no longer the dry look's to carry.
func TestDryHealthFollowsAModelWithoutAWrite(t *testing.T) {
	root := filepath.Join(sandbox(t), "custom-grok")
	t.Setenv("GROK_HOME", root)
	home := grokSummarySeat(t, root, "", "")
	write(t, filepath.Join(home, ".agentkit", "config.toml"), grokConfig+
		"[models.swift]\nharness='grokbuild'\nmodel='grok-other'\neffort='high'\nprovider='pool'\n[providers.pool]\nmode='subscription'\naccounts=['a','b']\n")
	drawn(t, home, "acme", grokTrust)
	dry := func() bool {
		t.Helper()
		before := tree(t, home)
		carried, _ := Health("acme", func(Live) bool { return true }, func(line string) { t.Fatalf("said %q", line) }, true)
		if after := tree(t, home); !maps.Equal(after, before) {
			t.Fatalf("the dry look changed HOME: %v", after)
		}
		return carried
	}
	if !dry() {
		t.Fatal("a seat on its own model was not carried")
	}
	write(t, filepath.Join(root, "sessions", grokSummaryDir, "conv-acme", "summary.json"), `{"current_model_id":"grok-other","reasoning_effort":"low"}`)
	if dry() {
		t.Fatal("the dry look read the model the record names, not the one it follows")
	}
}

// tree is every path under root with what it holds, a folder holding "".
func tree(t *testing.T, root string) map[string]string {
	t.Helper()
	found := map[string]string{}
	err := filepath.WalkDir(root, func(path string, entry fs.DirEntry, err error) error {
		if err != nil || entry.IsDir() {
			found[path] = ""
			return err
		}
		data, err := os.ReadFile(path)
		found[path] = string(data)
		return err
	})
	if err != nil {
		t.Fatal(err)
	}
	return found
}
