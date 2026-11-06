//go:build unix

package features

import (
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

// A features command's answer, or the one line saying why there is none, as Python's
// gitcall.project_answer and menu.switch_rows read it.
func TestTheProjectsCommandAnswersOrSaysWhy(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	for _, each := range []struct{ script, why string }{
		{`echo '[{"id": "dark", "you": true}, {"name": "no id"}, {"id": "fixed", "name": "Locked", "everyone": true, "you_switchable": false}]'`, ""},
		{`echo '{"id": "dark"}'`, "list answered no list"},
		{`echo nope`, "list answered no JSON"},
		{`printf 'warming up\nno route to production\n' >&2; exit 1`, "no route to production"},
		{`exit 2`, "list exited 2"},
	} {
		checkout := t.TempDir()
		script := filepath.Join(checkout, "features.sh")
		if err := os.WriteFile(script, []byte(each.script+"\n"), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(checkout, "AGENTS.md"), []byte("---\nfeatures: sh "+script+"\n---\n"), 0o644); err != nil {
			t.Fatal(err)
		}
		found := &entry{}
		list(checkout, found)
		if found.Why != each.why {
			t.Errorf("%s: said %q, want %q", each.script, found.Why, each.why)
		}
		if each.why == "" {
			want := []Switch{{ID: "dark", Name: "dark", You: true}, {ID: "fixed", Name: "Locked", Everyone: true, Fixed: true}}
			if !reflect.DeepEqual(found.Rows, want) {
				t.Errorf("rows %+v, want %+v", found.Rows, want)
			}
		} else if found.Rows != nil {
			t.Errorf("%s: rows %+v from no list", each.script, found.Rows)
		}
	}
}
