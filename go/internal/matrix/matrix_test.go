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

	"agentkit/internal/boards"
	"agentkit/internal/listing"
	"agentkit/internal/quality"
	"agentkit/internal/run"
)

func index(names ...string) map[string][]hit {
	found := map[string][]hit{}
	for _, name := range names {
		found[normal(name)] = append(found[normal(name)], hit{name, &boards.Release{Slug: name}})
	}
	return found
}

func TestAModelIsFoundUnderTheNamesABoardGivesIt(t *testing.T) {
	for _, each := range []struct {
		names []string
		model string
		want  []string
	}{
		{[]string{"Acme 5"}, "provider/acme-5", []string{"Acme 5"}},
		{[]string{"Acme Pro"}, "acme-pro-1.0", []string{"Acme Pro"}},
		{[]string{"Acme 5"}, "acme-5-5", nil}, // a board's name with its own version: another model
		{[]string{"Acme 5 (Default Fallback)"}, "acme-5", []string{"Acme 5 (Default Fallback)"}},
		{[]string{"Acme 5 (One)", "Acme 5 (Two)"}, "acme-5", nil},
		{[]string{"Acme Flash 1017", "Acme Flash 1102"}, "acme-flash", []string{"Acme Flash 1017", "Acme Flash 1102"}},
		{[]string{"Acme 5"}, "acme-5-free", []string{"Acme 5"}},
		{[]string{"Acme 5"}, "bolt-3", nil},
	} {
		var got []string
		for _, one := range found(index(each.names...), each.model) {
			got = append(got, one.model)
		}
		if len(got) > 1 {
			// a map's order; lineup keeps only that all are one release
			if got[0] > got[1] {
				got[0], got[1] = got[1], got[0]
			}
		}
		if !reflect.DeepEqual(got, each.want) {
			t.Errorf("%s in %v: %v", each.model, each.names, got)
		}
	}
}

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
		found, err := Refresh(false, true)
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

func TestAMarkOfAReplacedReleaseMarksWhatReplacedIt(t *testing.T) {
	state, _ := home(t)
	row := func(slug, to string) string {
		deprecated, next := "false", "null"
		if to != "" {
			deprecated, next = "true", `"`+to+`"`
		}
		return fmt.Sprintf(`{"model": %q, "effort": null, "slug": %q, "maker": "Acme", "deprecated": %s, "values": {}, "release": {"slug": %q, "name": %q, "deprecatedTo": %s}}`,
			slug, slug, deprecated, slug, slug, next)
	}
	cached := `{"artificialanalysis.ai": {"rows": [` + row("old", "new") + "," + row("new", "") + "," + row("kept", "") + "," + row("nowhere", "gone") + `]}}`
	if err := os.WriteFile(filepath.Join(state, "boards.json"), []byte(cached), 0o666); err != nil {
		t.Fatal(err)
	}
	if marked, err := Compared(nil); err != nil || marked != nil {
		t.Fatalf("no marks: %v %v", marked, err)
	}
	config := filepath.Join(os.Getenv("HOME"), ".agentkit", "config.toml")
	data, err := os.ReadFile(config)
	if err != nil {
		t.Fatal(err)
	}
	marks := `compare = ["old", "kept", "nowhere", "never-listed"]` + "\n"
	if err := os.WriteFile(config, []byte(marks+string(data)), 0o666); err != nil {
		t.Fatal(err)
	}
	marked, err := Compared([]quality.Row{{Release: "new"}, {Release: "kept"}})
	if err != nil {
		t.Fatal(err)
	}
	if want := map[string]bool{"new": true, "kept": true}; !reflect.DeepEqual(marked, want) {
		t.Fatalf("marked %v", marked)
	}
}
