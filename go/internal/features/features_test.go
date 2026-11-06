//go:build unix

package features

import (
	"os"
	"path/filepath"
	"reflect"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"

	"agentkit/internal/host"
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

// A shell that answers and exits while what it started holds its output open has no answer by the
// wait, and what it started goes with its session then.
func TestPastTheWaitWhatTheCommandStartedGoesToo(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	before := wait
	wait = 200 * time.Millisecond
	t.Cleanup(func() { wait = before })
	checkout := t.TempDir()
	script := "sleep 60 & echo $! >child.pid; echo '[]'\n"
	if err := os.WriteFile(filepath.Join(checkout, "features.sh"), []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(checkout, "AGENTS.md"), []byte("---\nfeatures: sh features.sh\n---\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	_, why := run(checkout, "list")
	data, err := os.ReadFile(filepath.Join(checkout, "child.pid"))
	pid, unread := strconv.Atoi(strings.TrimSpace(string(data)))
	if err != nil || unread != nil {
		t.Fatal(err, unread)
	}
	defer syscall.Kill(pid, syscall.SIGKILL)
	if !strings.HasPrefix(why, "list: no answer in ") {
		t.Errorf("said %q", why)
	}
	for until := time.Now().Add(time.Second); time.Now().Before(until); time.Sleep(10 * time.Millisecond) {
		if stat, ok := host.ReadStat(pid); syscall.Kill(pid, 0) != nil || ok && stat.Exited() {
			return
		}
	}
	t.Fatal("what the command started still runs past the wait")
}

// A wait over before the command starts is no answer, and stops nothing it never started.
func TestAWaitOverBeforeTheCommandStartsIsNoAnswer(t *testing.T) {
	t.Setenv("HOME", t.TempDir())
	before := wait
	wait = time.Nanosecond
	t.Cleanup(func() { wait = before })
	checkout := t.TempDir()
	if err := os.WriteFile(filepath.Join(checkout, "AGENTS.md"), []byte("---\nfeatures: echo '[]'\n---\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if _, why := run(checkout, "list"); !strings.HasPrefix(why, "list: no answer in ") {
		t.Errorf("said %q", why)
	}
	time.Sleep(10 * time.Millisecond) // for a stop the deadline set off to have run
}
