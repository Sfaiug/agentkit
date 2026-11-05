//go:build unix

package tick

import (
	"bytes"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentkit/internal/run"
)

func goneHome(t *testing.T) (ak, path string) {
	t.Helper()
	ak, _ = idleHome(t, answers)
	bin := strings.Split(os.Getenv("PATH"), string(os.PathListSeparator))[0]
	put(t, filepath.Join(bin, "tmux"), "#!/bin/sh\nexit 1\n")
	if err := os.Chmod(filepath.Join(bin, "tmux"), 0o700); err != nil {
		t.Fatal(err)
	}
	put(t, filepath.Join(ak, "config.toml"), "[audit]\non=false\n[models.opus]\nharness='claude'\nmodel='claude-opus'\neffort='xhigh'\nprovider='test'\n[providers.test]\nmode='subscription'\n")
	path = filepath.Join(ak, "state", "session-acme.json")
	put(t, path, `{"orchestrator":"opus","workers":["opus"],"conversation":"conv-acme","id_source":"launcher","resumable":true,"created":1,"repo":null}`)
	return ak, path
}

func TestTickReadsGoneSeatsAndLeavesRevivalAndCardsToPython(t *testing.T) {
	for _, each := range []struct {
		name, plan, file, hook, word string
		carried                      bool
	}{
		{"resting", "", `{}`, "", "idle", true},
		{"closed owing", "- [ ] Last\n", fmt.Sprintf(`{"stopped_at":%d,"closed_by_owner":true}`, time.Now().Unix()), "", "idle", true},
		{"open work", "- [ ] Last\n", `{}`, "", "needs you", true},
		{"finished", "- [x] Last\n", `{}`, "", "done", true},
		{"cut off turn", "", `{"state":"working"}`, "", "idle", false},
		{"newer stop", "", `{"state":"working"}`, "Stop", "idle", true},
		{"newer prompt", "", `{}`, "UserPromptSubmit", "idle", false},
		{"unknown hook", "", `{"state":"working"}`, "Unknown", "idle", false},
	} {
		t.Run(each.name, func(t *testing.T) {
			ak, path := goneHome(t)
			put(t, filepath.Join(ak, "state", "seat-acme.json"), each.file)
			if each.plan != "" {
				put(t, filepath.Join(ak, "state", "plan-acme.md"), each.plan)
			}
			if each.hook != "" {
				put(t, filepath.Join(ak, "state", "hook-acme.json"), `{"event":"`+each.hook+`","at":2}`)
			}
			var out, errOut bytes.Buffer
			if got := carries(&out, &errOut); got != each.carried {
				t.Fatalf("carried=%v: %s %s", got, &out, &errOut)
			}
			file, _ := run.ReadJSON(filepath.Join(ak, "state", "seat-acme.json"))
			if file.Str("word") != each.word {
				t.Fatal(run.Line(file))
			}
			if each.carried {
				record, _ := run.ReadJSON(path)
				seen := record.Get("seen")
				if !record.Truthy("seen") || !carries(&out, &errOut) {
					t.Fatalf("second tick: %s %s; record=%s", &out, &errOut, run.Line(record))
				}
				record, _ = run.ReadJSON(path)
				if !run.Equal(record.Get("seen"), seen) {
					t.Fatal("an absent seat's retention clock moved")
				}
			}
		})
	}
}

func TestTickSkipsARecordItsHarnessDoesNotOwn(t *testing.T) {
	ak, path := goneHome(t)
	record, _ := run.ReadJSON(path)
	record.Delete("id_source")
	put(t, path, run.Line(record))
	var out, errOut bytes.Buffer
	if !carries(&out, &errOut) {
		t.Fatalf("left to Python: %s %s", &out, &errOut)
	}
	if _, err := os.Stat(filepath.Join(ak, "state", "seat-acme.json")); !os.IsNotExist(err) {
		t.Fatalf("a record with no seat got a word: %v", err)
	}
}
