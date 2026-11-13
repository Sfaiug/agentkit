package move

import (
	"bytes"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"agentkit/internal/install"
)

func TestPartsNameEachFolderAboveWhatIsAsked(t *testing.T) {
	want := []string{"/", "/.agentkit", "/.agentkit/tmp", "/.local", "/.local/share", "/.local/share/browser-bridge",
		"/.local/share/browser-bridge/profile", "/.ssh", "/.ssh/authorized_keys"}
	if got := parts("/"); !reflect.DeepEqual(got, want) {
		t.Fatalf("parts = %q, want %q", got, want)
	}
}

// machine is a temporary HOME and a PATH with this ssh and an rsync that logs its words and exits
// with `rsyncCode`; ssh logs its words too, so a test sees what the other machine was handed.
func machine(t *testing.T, ssh, rsyncCode string) (home, log string) {
	t.Helper()
	root := t.TempDir()
	home, log = filepath.Join(root, "home"), filepath.Join(root, "log")
	tools := filepath.Join(root, "tools")
	for _, dir := range []string{home, tools} {
		if err := os.Mkdir(dir, 0700); err != nil {
			t.Fatal(err)
		}
	}
	logs := `printf '%s\n' "$0" "$@" >>` + log + "\n"
	for name, body := range map[string]string{"ssh": logs + ssh, "rsync": logs + "exit " + rsyncCode} {
		if err := os.WriteFile(filepath.Join(tools, name), []byte("#!/bin/sh\n"+body+"\n"), 0700); err != nil {
			t.Fatal(err)
		}
	}
	t.Setenv("HOME", home)
	t.Setenv("PATH", tools+":"+os.Getenv("PATH"))
	return home, log
}

func run(args ...string) (int, string) {
	var out, errOut bytes.Buffer
	code := Main(args, &out, &errOut)
	return code, errOut.String()
}

func TestUsage(t *testing.T) {
	for _, args := range [][]string{{}, {"a", "b"}, {"-x"}} {
		if code, said := run(args...); code != 2 || said != "ak move: usage: ak move ALIAS\n" {
			t.Fatalf("%q: exit %d, %q", args, code, said)
		}
	}
}

func TestALinkHereRefusesWithoutAskingTheOtherMachine(t *testing.T) {
	home, log := machine(t, "exit 1", "0")
	if err := os.Symlink(t.TempDir(), filepath.Join(home, ".ssh")); err != nil {
		t.Fatal(err)
	}
	code, said := run("acme-mini")
	if want := "ak move: refused: " + home + "/.ssh is a link here\n"; code != 1 || said != want {
		t.Fatalf("exit %d, %q, want %q", code, said, want)
	}
	if _, err := os.Stat(log); !os.IsNotExist(err) {
		t.Fatalf("something ran: %v", err)
	}
}

func TestEveryRefusalOfTheOtherMachineInItsOrder(t *testing.T) {
	home, log := machine(t, "printf 'link /a\\nhome /other\\nhere\\ntick\\nlink /a/b\\n'", "0")
	code, said := run("acme-mini")
	want := "ak move: refused: acme-mini is this machine\n" +
		"ak move: refused: the home on acme-mini is not " + home + "\n" +
		"ak move: refused: ak's tick is in the crontab on acme-mini, or that crontab cannot be read\n" +
		"ak move: refused: /a is a link on acme-mini\n" +
		"ak move: refused: /a/b is a link on acme-mini\n"
	if code != 1 || said != want {
		t.Fatalf("exit %d, %q, want %q", code, said, want)
	}
	logged, _ := os.ReadFile(log)
	if strings.Contains(string(logged), "rsync") {
		t.Fatalf("copied after a refusal: %s", logged)
	}
}

func TestAProbeThatFailsIsNoCopy(t *testing.T) {
	_, log := machine(t, "exit 255", "0")
	if code, said := run("acme-mini"); code != 2 || said != "ak move: `ssh acme-mini` failed\n" {
		t.Fatalf("exit %d, %q", code, said)
	}
	logged, _ := os.ReadFile(log)
	if strings.Contains(string(logged), "rsync") {
		t.Fatalf("copied after a failed probe: %s", logged)
	}
}

func TestTheCopy(t *testing.T) {
	for rsyncCode, want := range map[string]int{"0": 0, "24": 0, "23": 23} {
		home, log := machine(t, `printf 'home %s\n' "$HOME"; ls -a "$HOME" | grep '^\.ak-move-' >&2 || exit 9`, rsyncCode)
		if code, said := run("acme-mini"); code != want || !strings.HasPrefix(said, ".ak-move-") {
			t.Fatalf("rsync %s: exit %d, %q", rsyncCode, code, said)
		}
		entries, _ := os.ReadDir(home)
		if len(entries) != 0 {
			t.Fatalf("the token outlived the probe: %v", entries)
		}
		logged, _ := os.ReadFile(log)
		_, words, _ := strings.Cut(string(logged), "rsync\n")
		wanted := strings.Join([]string{"-aH", "--no-D", "--delete", "--info=progress2",
			"--exclude=/.agentkit/tmp", "--exclude=/.ssh/authorized_keys",
			"--exclude=/.local/share/browser-bridge/profile/SingletonLock",
			"--exclude=/.local/share/browser-bridge/profile/SingletonSocket",
			"--exclude=/.local/share/browser-bridge/profile/SingletonCookie",
			home + "/", "acme-mini:" + home + "/"}, "\n") + "\n"
		if words != wanted {
			t.Fatalf("rsync's words %q, want %q", words, wanted)
		}
		if !strings.Contains(string(logged), `grep -qE '"'"'`+install.CronTagged.String()+`'"'"'`) {
			t.Fatalf("the tick's match was not asked: %s", logged)
		}
	}
}
