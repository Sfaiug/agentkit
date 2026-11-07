package config

import (
	"os"
	"reflect"
	"strings"
	"testing"
)

// A model taken out on Models and back brings its provider's table back as the page keeps it: as the
// page opened, or as the page first took a model of it in or out, whatever changed in the config
// since (menu.models_page's `tables`).
func TestATableComesBackAsThePageKeptIt(t *testing.T) {
	path := rememberIn(t, tickModels+`
[models.zen]
harness = 'acme'
model = 'zen/z0'
effort = 'high'
provider = 'zen'

[providers.zen]
mode = 'free'
usage_model = 'zen'
`)
	ticks, err := OpenModelTicks()
	if err != nil {
		t.Fatal(err)
	}
	tick := func(id, label string, under *Listed) {
		t.Helper()
		if err := ticks.Tick("acme", id, label, []string{"high"}, under, noKeep); err != nil {
			t.Fatal(err)
		}
	}
	provider := func(name string) any {
		t.Helper()
		data, _ := os.ReadFile(path)
		root, err := parseDocument(string(data))
		if err != nil {
			t.Fatal(err)
		}
		return plain(root.get("providers").(*table).get(name))
	}
	// changed is the config with a change no page here made, as another open page makes one
	changed := func(old, new string) {
		t.Helper()
		data, _ := os.ReadFile(path)
		if !strings.Contains(string(data), old) {
			t.Fatalf("no %q in %s", old, data)
		}
		if err := os.WriteFile(path, []byte(strings.Replace(string(data), old, new, 1)), 0o600); err != nil {
			t.Fatal(err)
		}
	}

	// a free provider's last model, its usage_model too: out takes its table, back brings it all
	opened := map[string]any{"mode": "free", "usage_model": "zen"}
	for range 2 {
		tick("zen/z0", "Zen", nil)
		if got := provider("zen"); got != nil {
			t.Fatalf("a free provider stayed without a model: %v", got)
		}
		tick("zen/z0", "Zen", nil)
		if got := provider("zen"); !reflect.DeepEqual(got, opened) {
			t.Fatalf("zen came back as %v, want %v", got, opened)
		}
	}

	// a provider a host lists, taken in here: back as first taken in, whatever changed since
	nova := &Listed{ID: "nova", Name: "Nova Cloud", Mode: "free"}
	tick("nova/n1", "Nova One", nova)
	taken := map[string]any{"mode": "free", "name": "Nova Cloud"}
	if got := provider("nova"); !reflect.DeepEqual(got, taken) {
		t.Fatalf("nova taken in as %v, want %v", got, taken)
	}
	changed("name = \"Nova Cloud\"", "name = \"Nova Cloud\"\nusage_model = \"nova-one\"")
	for range 2 {
		tick("nova/n1", "Nova One", nova)
		if got := provider("nova"); got != nil {
			t.Fatalf("a free provider stayed without a model: %v", got)
		}
		tick("nova/n1", "Nova One", nova)
		if got := provider("nova"); !reflect.DeepEqual(got, taken) {
			t.Fatalf("nova came back as %v, want %v", got, taken)
		}
		changed("name = \"Nova Cloud\"", "name = \"Nova\"")
	}

	// a free provider and its model another open page put in: out takes the table as it was, and
	// another page's save in between cannot lose what comes back
	changed("[providers.fuel]", "[models.vega]\nharness = 'acme'\nmodel = 'vega/v1'\neffort = 'high'\nprovider = 'vega'\n\n"+
		"[providers.vega]\nmode = 'free'\nusage_model = 'vega'\nmetadata = {nested = [{values = [1, 2]}]}\n\n[providers.fuel]")
	other := provider("vega")
	tick("vega/v1", "Vega", nil)
	if got := provider("vega"); got != nil {
		t.Fatalf("a free provider stayed without a model: %v", got)
	}
	if err := RememberDefaults("one", []string{"one"}, nil, noKeep); err != nil {
		t.Fatal(err)
	}
	tick("vega/v1", "Vega", nil)
	if got := provider("vega"); !reflect.DeepEqual(got, other) {
		t.Fatalf("vega came back as %v, want %v", got, other)
	}
}
