package config

import (
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

func TestRememberCompareKeepsEveryOtherValue(t *testing.T) {
	text := `# original comment
extra = {deep = {k = 1}}
within = 2.5
compare = ["old"]

[defaults]
orchestrator = "acme"
workers = ["acme"]
reviewers = ["acme"]
unknown = "kept"

[models.acme]
harness = "echo"
model = "echo-1"
effort = "low"
provider = "test"
extra = [1, 2]

[providers.test]
mode = "subscription"
unknown = true

[[custom.entries]]
name = "one"
[[custom.entries]]
name = "two"
`
	path := rememberIn(t, text)
	want, err := ReadTOML(text)
	if err != nil {
		t.Fatal(err)
	}
	for _, marks := range [][]string{{"acme-5", "bolt-3"}, nil} {
		prepared := false
		if err := RememberCompare(marks, func() error {
			prepared = true
			if data, err := os.ReadFile(path); err != nil || string(data) != text {
				t.Fatalf("config replaced before record preparation: %s %v", data, err)
			}
			return nil
		}); err != nil {
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
		delete(want, "compare")
		if len(marks) > 0 {
			want["compare"] = listed(marks)
		}
		if !prepared || !reflect.DeepEqual(got, want) || !strings.HasPrefix(string(data), strings.Join(saveHeader, "\n")) {
			t.Fatalf("save changed other values or skipped preparation: %s", data)
		}
		if info, err := os.Stat(path); err != nil || info.Mode().Perm() != 0o600 {
			t.Fatalf("config permissions: %v %v", info, err)
		}
		text = string(data)
	}
}

func TestRememberCompareLeavesTheConfigWhenRecordPreparationFails(t *testing.T) {
	modelsHome(t, "compare = ['old']\n")
	path := filepath.Join(Home(), "config.toml")
	before, _ := os.ReadFile(path)
	failure := errors.New("record locked")
	if err := RememberCompare([]string{"new"}, func() error { return failure }); !errors.Is(err, failure) {
		t.Fatal(err)
	}
	if after, _ := os.ReadFile(path); string(after) != string(before) {
		t.Fatalf("failed save changed config: %s", after)
	}
	if _, err := os.Stat(filepath.Join(Home(), "config.tmp")); !os.IsNotExist(err) {
		t.Fatalf("temporary file left: %v", err)
	}
}
