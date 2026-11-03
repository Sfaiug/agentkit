package listing

import (
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"testing"
)

// adapter is a harness whose `models` verb runs body, with table its manifest's rest.
func adapter(t *testing.T, body, table string) {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Skip("the fake adapter is a shell script")
	}
	root := t.TempDir()
	t.Setenv("HOME", root)
	t.Setenv("USERPROFILE", root)
	adapters := filepath.Join(root, "adapters")
	if err := os.MkdirAll(adapters, 0o777); err != nil {
		t.Fatal(err)
	}
	t.Setenv("AGENTKIT_ADAPTER_DIR", adapters)
	if err := os.WriteFile(filepath.Join(adapters, "acme.toml"), []byte("name = \"acme\"\n"+table), 0o666); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(adapters, "acme.sh"), []byte("#!/bin/sh\n"+body+"\n"), 0o777); err != nil {
		t.Fatal(err)
	}
}

const table = "[catalog]\ntable-1 = { efforts = [\"low\", \"high\"] }\n"

func TestAListedModelIsTakenOnceAsFirstSaid(t *testing.T) {
	adapter(t, `printf 'acme-1\tAcme\tlow high\nacme-2\tTwo\t\nacme-1\tAgain\tmax\nnot a line\n'`, table)
	models, err := Catalog("acme")
	if err != nil {
		t.Fatal(err)
	}
	if want := []Model{{"acme-1", []string{"low", "high"}}, {"acme-2", []string{}}}; !reflect.DeepEqual(models, want) {
		t.Fatalf("%+v", models)
	}
}

func TestAListingThatFailsLeavesTheManifestsTable(t *testing.T) {
	adapter(t, "echo 'acme-1\tAcme\tlow'; exit 1", table)
	models, err := Catalog("acme")
	if err != nil {
		t.Fatal(err)
	}
	if want := []Model{{"table-1", []string{"low", "high"}}}; !reflect.DeepEqual(models, want) {
		t.Fatalf("%+v", models)
	}
}
