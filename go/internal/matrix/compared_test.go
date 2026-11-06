package matrix

import (
	"os"
	"path/filepath"
	"reflect"
	"testing"

	"agentkit/internal/quality"
	"agentkit/internal/run"
)

// Your companies are the makers of what [defaults] runs unless `companies` names them, and of
// theirs every listed release is on but those `models_off` holds, a next one on by itself.
func TestOnlyTheModelsOnInYourCompaniesAreCompared(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	if err := os.MkdirAll(filepath.Join(home, ".agentkit"), 0o777); err != nil {
		t.Fatal(err)
	}
	scored := func(release, maker string, runners ...[2]string) quality.Row {
		values := run.NewObject()
		for _, column := range []string{"aa.intelligenceIndex", "aa.frontierCode20", "aa.terminalBench40", "arena.agent"} {
			values.Set(column, 50.0)
		}
		return quality.Row{Release: release, Maker: maker, Values: values, Runners: runners}
	}
	unscored := scored("acme-flash", "Acme", [2]string{"echo", "echo-1"})
	unscored.Values = run.NewObject()
	rows := []quality.Row{scored("acme-5", "Acme", [2]string{"echo", "echo-1"}), scored("acme-6", "Acme"),
		scored("bolt-3", "Bolt"), unscored}
	for _, example := range []struct {
		settings string
		on       []string
		ours     int
	}{
		{"", []string{"acme-5", "acme-6"}, 2},
		{"models_off = ['acme-6', 'bolt-3']\n", []string{"acme-5"}, 2},
		{"companies = ['Bolt']\n", []string{"bolt-3"}, 1},
		{"companies = []\n", []string{}, 0},
	} {
		text := example.settings + "[models.mine]\nharness = 'echo'\nmodel = 'echo-1'\neffort = 'low'\nprovider = 'p'\n[providers.p]\nmode = 'subscription'\n"
		if err := os.WriteFile(filepath.Join(home, ".agentkit", "config.toml"), []byte(text), 0o666); err != nil {
			t.Fatal(err)
		}
		on, ours, err := Compared(rows)
		want := map[string]bool{}
		for _, release := range example.on {
			want[release] = true
		}
		if err != nil || !reflect.DeepEqual(on, want) || ours != example.ours {
			t.Errorf("%q: on %v, %d ours (%v)", example.settings, on, ours, err)
		}
	}
}
