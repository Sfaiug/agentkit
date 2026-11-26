package config

import (
	"fmt"
	"os"
	"reflect"
	"testing"
)

// A save of a machine's marks writes, where the old switch still stands, the work it implied in
// each table naming none, and drops the switch; a table's own marks and every other key stay.
func TestAMachineSaveWritesWhatTheOldSwitchImplied(t *testing.T) {
	path := rememberIn(t, `turns_on_machines = true
suite_helper = "acme-linux"

[defaults]
orchestrator = "acme"
workers = ["acme"]

[models.acme]
harness = "echo"
model = "echo-1"
effort = "low"
provider = "test"

[providers.test]
mode = "subscription"

[machines.acme-mac]
work = ["tests"]
`)
	implied := []Marks{{"acme-mac", []string{"turns", "tests"}}, {"acme-linux", []string{"turns", "tests"}}}
	if err := SaveMachine("acme-new", []string{"tests"}, implied, func() error { return nil }); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	got, err := ReadTOML(string(data))
	if err != nil {
		t.Fatal(err)
	}
	if _, held := got["turns_on_machines"]; held || got["suite_helper"] != "acme-linux" {
		t.Fatalf("top level: %s", data)
	}
	want := map[string]any{
		"machines": map[string]any{"acme-mac": map[string]any{"work": []any{"tests"}},
			"acme-linux": map[string]any{"work": []any{"turns", "tests"}}, "acme-new": map[string]any{"work": []any{"tests"}}},
	}
	for key, value := range want {
		if fmt.Sprint(got[key]) != fmt.Sprint(value) {
			t.Errorf("%s: %#v, want %#v", key, got[key], value)
		}
	}
	if work, known := MachineWork("acme-linux"); !known || !reflect.DeepEqual(work, []string{"turns", "tests"}) {
		t.Errorf("read back: %v %v", work, known)
	}
}
