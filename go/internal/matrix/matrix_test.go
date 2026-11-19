package matrix

import (
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"strings"
	"testing"
	"time"

	"agentkit/internal/listing"
	"agentkit/internal/run"
)

func heldBoards(t *testing.T, rows string) *run.Object {
	t.Helper()
	value, err := run.Decode([]byte(`{"artificialanalysis.ai": {"rows": [` + rows + `]}}`))
	if err != nil {
		t.Fatal(err)
	}
	return value.(*run.Object)
}

func boardRow(release, effort string) string {
	word, slug := "null", release
	if effort != "" {
		word, slug = `"`+effort+`"`, release+"-"+effort
	}
	if effort == "high" {
		slug = release // the release's own slug: its default effort
	}
	return fmt.Sprintf(`{"model": %q, "effort": %s, "slug": %q, "maker": "Acme", "deprecated": false, "values": {"aa.intelligenceIndex": 50}, "release": {"slug": %q, "name": %q, "deprecatedTo": null}}`,
		release, word, slug, release, release)
}

func TestYoursIsEachModelOfAHarnessAtTheEffortsItLists(t *testing.T) {
	held := heldBoards(t, strings.Join([]string{boardRow("acme", "low"), boardRow("acme", "high"), boardRow("acme", "max"), boardRow("bolt", "")}, ","))
	rows := lineup(held, []any{"one", "two"}, map[string][]listing.Model{
		"one": {{ID: "acme", Efforts: []string{"low", "high"}}, {ID: "bolt", Efforts: []string{"low"}}},
		"two": {{ID: "acme", Efforts: []string{"none"}}, {ID: "not-listed", Efforts: nil}},
	})
	got := map[string]string{}
	for _, value := range rows {
		row := value.(*run.Object)
		got[row.Str("release")+"/"+row.Str("effort")] = run.Line(row.Get("yours"))
	}
	one := `{"harness": "one", "model": "acme"}`
	want := map[string]string{
		"acme/low":  "[" + one + "]",
		"acme/high": "[" + one + `, {"harness": "two", "model": "acme"}]`, // `none` alone runs at the default
		"acme/max":  "[]",
		"bolt/":     `[{"harness": "one", "model": "bolt"}]`, // a row naming no effort is the model however run
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("yours %v, want %v", got, want)
	}
}

func TestAReleaseWhoseNameSaysNothingIsLabelledByItsSlug(t *testing.T) {
	t.Setenv("AGENTKIT_ADAPTER_DIR", t.TempDir())
	for _, raw := range []string{"null", "7", `"  \n"`, `"\u001f"`, `"---"`} {
		held := heldBoards(t, `{"model": "x", "effort": null, "slug": "acme-bevel-1", "maker": "Acme", "deprecated": false, "values": {}, "release": {"slug": "acme-bevel-1", "name": `+raw+`, "deprecatedTo": null}}`)
		row := lineup(held, nil, nil)[0].(*run.Object)
		if got := row.Str("name"); got != "Acme Bevel 1" {
			t.Errorf("name %s: got %q, want Acme Bevel 1", raw, got)
		}
	}
}

// home is a config whose one harness counts its listings and a board fresh enough to ask nothing.
func home(t *testing.T) (state string, listings func() int) {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Skip("the fake adapter is a shell script")
	}
	root := t.TempDir()
	t.Setenv("HOME", root)
	adapters := filepath.Join(root, "adapters")
	bin := filepath.Join(root, "bin")
	state = filepath.Join(root, ".agentkit", "state")
	for _, dir := range []string{adapters, bin, state} {
		if err := os.MkdirAll(dir, 0o777); err != nil {
			t.Fatal(err)
		}
	}
	t.Setenv("AGENTKIT_ADAPTER_DIR", adapters)
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
	log := filepath.Join(root, "log")
	write := func(path, text string, mode os.FileMode) {
		t.Helper()
		if err := os.WriteFile(path, []byte(text), mode); err != nil {
			t.Fatal(err)
		}
	}
	write(filepath.Join(adapters, "acme.toml"), "name = \"acme\"\n", 0o666)
	write(filepath.Join(adapters, "acme.sh"), "#!/bin/sh\necho x >> '"+log+"'\nprintf 'acme\\tAcme\\thigh\\n'\n", 0o777)
	write(filepath.Join(bin, "acme"), "#!/bin/sh\n", 0o777)
	writeConfig(t, "high")
	now := time.Now().Unix()
	write(filepath.Join(state, "boards.json"), fmt.Sprintf(`{"artificialanalysis.ai": {"asked_at": %d, "fetched_at": %d, "rows": [%s], "error": null, "build": ""}, "arena.ai": {"asked_at": %d, "fetched_at": %d, "rows": [], "error": null, "build": ""}}`,
		now, now, boardRow("acme", "high"), now, now), 0o666)
	return state, func() int {
		data, _ := os.ReadFile(log)
		return strings.Count(string(data), "x")
	}
}

func writeConfig(t *testing.T, effort string) {
	t.Helper()
	text := "[models.mine]\nharness = \"acme\"\nmodel = \"acme\"\neffort = \"" + effort + "\"\nprovider = \"p\"\n[providers.p]\nmode = \"subscription\"\n"
	home, _ := os.UserHomeDir()
	if err := os.MkdirAll(filepath.Join(home, ".agentkit"), 0o777); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(home, ".agentkit", "config.toml"), []byte(text), 0o666); err != nil {
		t.Fatal(err)
	}
}

func TestTheLineupIsReusedUntilSomethingItWasComputedFromChanges(t *testing.T) {
	state, listings := home(t)
	refresh := func() *Matrix {
		t.Helper()
		found, err := Refresh(false)
		if err != nil {
			t.Fatal(err)
		}
		return found
	}
	first := refresh()
	if listings() != 1 || len(first.Rows) != 1 || !first.Rows[0].Yours || first.Rows[0].Effort != "high" {
		t.Fatalf("listings %d rows %+v", listings(), first.Rows)
	}
	data, err := os.ReadFile(filepath.Join(state, "matrix.json"))
	if err != nil {
		t.Fatal(err)
	}
	matrix := stored()
	if !reflect.DeepEqual(matrix.Keys(), []string{"computed_at", "config", "harnesses", "build", "lineup", "fetched_at"}) {
		t.Fatalf("matrix.json holds %s", data)
	}
	if got := run.Line(matrix.Get("config")); got != `[["mine", "acme", "acme", "high", "high", "high"]]` {
		t.Fatalf("config key %s", got)
	}
	again := refresh()
	if listings() != 1 || again.Fetched != first.Fetched || len(again.Rows) != 1 {
		t.Fatalf("a lineup that holds was computed again: %d", listings())
	}
	writeConfig(t, "low")
	refresh()
	if listings() != 2 {
		t.Fatalf("the config changed and nothing was asked: %d", listings())
	}
	refresh()
	if listings() != 2 {
		t.Fatalf("listings %d", listings())
	}
	// a harness gone
	if err := os.Rename(filepath.Join(os.Getenv("HOME"), "bin", "acme"), filepath.Join(os.Getenv("HOME"), "bin", "other")); err != nil {
		t.Fatal(err)
	}
	gone := refresh()
	if listings() != 2 || gone.Rows[0].Yours {
		t.Fatalf("a harness gone: %d %+v", listings(), gone.Rows)
	}
	// a stored lineup of another build is computed again, whatever it holds
	if err := os.Rename(filepath.Join(os.Getenv("HOME"), "bin", "other"), filepath.Join(os.Getenv("HOME"), "bin", "acme")); err != nil {
		t.Fatal(err)
	}
	refresh()
	asked := listings()
	stale := stored()
	stale.Set("build", "another")
	whole := run.NewObject()
	whole.Set("matrix", stale)
	if err := write(whole); err != nil {
		t.Fatal(err)
	}
	refresh()
	if listings() != asked+1 {
		t.Fatalf("another build's lineup stood: %d after %d", listings(), asked)
	}
}
