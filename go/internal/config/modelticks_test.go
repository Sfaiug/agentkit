package config

import (
	"bytes"
	"errors"
	"os"
	"reflect"
	"strings"
	"testing"
)

const tickModels = `[models.one]
harness = 'acme'
model = 'm0'
effort = 'xhigh'
provider = 'fuel'
x_custom = {nested = [1, 2]}

[providers.fuel]
mode = 'subscription'
unknown = 'keep'

[custom.deep]
value = 7
`

func TestModelTicksRestoreBytesAndNeverMaterializeOmittedDefaults(t *testing.T) {
	for _, defaults := range []string{"", "[defaults]\n", "[defaults]\nworkers = ['one']\n",
		"[defaults]\norchestrator = 'one'\n", "[defaults]\nreviewers = ['one']\n",
		"[defaults]\nworkers = ['gone', 'one']\n", "[defaults]\nworkers = ['model-one']\n"} {
		t.Run(defaults, func(t *testing.T) {
			before := "# the owner's formatting\nmax_runs=3\nx_custom='kept'\n\n" + defaults + tickModels
			path := rememberIn(t, before)
			ticks, err := OpenModelTicks()
			if err != nil {
				t.Fatal(err)
			}
			flip := func() {
				t.Helper()
				if err := ticks.Tick("acme", "m1", "Model One 2", []string{"low", "medium", "high"}, nil, noKeep); err != nil {
					t.Fatal(err)
				}
			}
			flip()
			data, _ := os.ReadFile(path)
			if !strings.HasPrefix(string(data), saveHeader[0]) {
				t.Fatalf("missing menu header: %s", data)
			}
			root, err := parseDocument(string(data))
			if err != nil {
				t.Fatal(err)
			}
			entry := root.get("models").(*table).get("model-one").(*table)
			want := map[string]any{"harness": "acme", "model": "m1", "effort": "high", "provider": "fuel"}
			if !reflect.DeepEqual(plain(entry), want) {
				t.Fatalf("added %v", plain(entry))
			}
			delete(root.get("models").(*table).values, "model-one")
			original, _ := parseDocument(before)
			got, _ := dump(root)
			wantText, _ := dump(original)
			if got != wantText {
				t.Fatalf("tick-in changed another value: %s", data)
			}
			flip()
			if data, _ := os.ReadFile(path); !bytes.Equal(data, []byte(before)) {
				t.Fatalf("tick-out changed original bytes: %s", data)
			}
			if info, err := os.Stat(path); err != nil || info.Mode().Perm() != 0o600 {
				t.Fatalf("config permissions: %v, %v", info, err)
			}
		})
	}
}

func TestModelTickRefusalsLeaveEveryByteAndSkipRecordPreparation(t *testing.T) {
	path := rememberIn(t, "# stays exactly\n"+tickModels)
	before, _ := os.ReadFile(path)
	ticks, err := OpenModelTicks()
	if err != nil {
		t.Fatal(err)
	}
	err = ticks.Tick("acme", "m0", "One", []string{"high"}, nil, func() error {
		t.Fatal("a refused removal prepared records")
		return nil
	})
	if err == nil {
		t.Fatal("removed the last model")
	}
	failed := errors.New("record preparation failed")
	if err := ticks.Tick("acme", "m1", "Two", []string{"high"}, nil, func() error { return failed }); err != failed {
		t.Fatalf("lost the save failure: %v", err)
	}
	if data, _ := os.ReadFile(path); !bytes.Equal(data, before) || len(ticks.Names("acme", "m1")) != 0 {
		t.Fatalf("refused edit changed config: %s", data)
	}
}

func TestTickOutPreservesChangesMadeSinceTickIn(t *testing.T) {
	path := rememberIn(t, tickModels)
	ticks, _ := OpenModelTicks()
	if err := ticks.Tick("acme", "m1", "Two", []string{"high"}, nil, noKeep); err != nil {
		t.Fatal(err)
	}
	on, _ := os.ReadFile(path)
	if err := os.WriteFile(path, append([]byte("concurrent = 17\n"), on...), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := ticks.Tick("acme", "m1", "Two", []string{"high"}, nil, noKeep); err != nil {
		t.Fatal(err)
	}
	data, _ := os.ReadFile(path)
	root, err := parseDocument(string(data))
	if err != nil || root.get("concurrent") == nil || root.get("defaults") != nil || len(ticks.Names("acme", "m1")) != 0 {
		t.Fatalf("lost a concurrent edit or added defaults: %s, %v", data, err)
	}
}
