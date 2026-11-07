//go:build unix

package features

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

// project is a checkout whose features command is script, its reading one feature off for all.
func project(t *testing.T, script string) (string, *entry) {
	t.Setenv("HOME", t.TempDir())
	checkout := t.TempDir()
	if err := os.WriteFile(filepath.Join(checkout, "features.sh"), []byte(script+"\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(checkout, "AGENTS.md"), []byte("---\nfeatures: sh features.sh\n---\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	found := &entry{Reading: Reading{Rows: []Switch{{ID: "dark", Name: "dark"}}}}
	held.Lock()
	known[checkout] = found
	held.Unlock()
	return checkout, found
}

func dark(found *entry) Switch {
	held.Lock()
	defer held.Unlock()
	return found.Rows[0]
}

// The row a `set` answers stands over a list asked before it answered, and over the one a flip
// asked before it was answering: the later flip's is drawn.
func TestAFlipsAnswerStandsOverOlderOnes(t *testing.T) {
	checkout, found := project(t, `echo "$*" >>calls.log
case $1 in list) echo '[{"id": "dark"}]' ;; *) while [ -e hold ]; do sleep 0.01; done; echo '{"id": "dark", "you": true}' ;; esac`)
	found.Asking = time.Now()
	if why := Flip(checkout, "dark", 0); why != "" || !dark(found).You {
		t.Fatalf("said %q, the row %+v", why, dark(found))
	}
	if calls, _ := os.ReadFile(filepath.Join(checkout, "calls.log")); string(calls) != "set dark you on\n" {
		t.Errorf("called %q", calls)
	}
	list(checkout, found)
	if !dark(found).You {
		t.Errorf("a list asked before the flip answered drew %+v", dark(found))
	}

	hold := filepath.Join(checkout, "hold")
	if err := os.WriteFile(hold, nil, 0o644); err != nil {
		t.Fatal(err)
	}
	found.Rows = []Switch{{ID: "dark", Name: "dark"}}
	said := make(chan string)
	go func() { said <- Flip(checkout, "dark", 0) }()
	for asked := 0; asked != 2; time.Sleep(time.Millisecond) {
		held.Lock()
		asked = found.flips["dark"]
		if asked == 2 {
			found.flips["dark"]++ // flipped again from the screen opened again
		}
		held.Unlock()
	}
	os.Remove(hold)
	if why := <-said; why != "" || dark(found).You {
		t.Errorf("said %q, a flip asked again drew %+v", why, dark(found))
	}
}

// A `set` that fails, or answers another row, says why in one line and changes no mark.
func TestAFailedFlipSaysWhyAndChangesNoMark(t *testing.T) {
	for _, each := range []struct{ script, why string }{
		{`echo 'production refused' >&2; exit 1`, "production refused"},
		{`echo '{"id": "beta", "you": true}'`, "set answered no row"},
	} {
		checkout, found := project(t, each.script)
		if why := Flip(checkout, "dark", 0); why != each.why || dark(found).You {
			t.Errorf("%s: said %q, the row %+v", each.script, why, dark(found))
		}
	}
}
