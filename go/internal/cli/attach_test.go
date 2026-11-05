package cli

import (
	"bytes"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

const hopNamed = "would run ssh -t acme-box ak --client\n"

func clientHome(t *testing.T, server string) string {
	t.Helper()
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	write(t, filepath.Join(home, ".agentkit", "state", "server"), server)
	return home
}

func TestTheAliasIsTheServerFileStripped(t *testing.T) {
	clientHome(t, "  acme-box \n")
	var out, errOut bytes.Buffer
	if code := Main([]string{"--dry-run", "--dry-run"}, &out, &errOut); code != 0 || out.String() != hopNamed || errOut.Len() != 0 {
		t.Fatalf("exit=%d stdout=%q stderr=%q", code, out.String(), errOut.String())
	}
}

func TestAClientWithAnAliasIsThePythonMenu(t *testing.T) {
	clientHome(t, "acme-box\n")
	for _, args := range [][]string{{"--client"}, {"--client", "--dry-run"}} {
		var out, errOut bytes.Buffer
		if code := Main(args, &out, &errOut); code != 3 || out.Len() != 0 {
			t.Fatalf("%v: exit=%d stdout=%q stderr=%q", args, code, out.String(), errOut.String())
		}
	}
}

func TestAnUnreadableServerFileIsNoAlias(t *testing.T) {
	home := clientHome(t, "")
	unreadable := filepath.Join(home, ".agentkit", "state", "server")
	if err := os.Remove(unreadable); err != nil {
		t.Fatal(err)
	}
	if err := os.Mkdir(unreadable, 0o700); err != nil { // reads as an error for any user, root too
		t.Fatal(err)
	}
	if alias := serverAlias(); alias != "" {
		t.Fatalf("alias=%q", alias)
	}
}

func TestAFlagNotTheMenusIsRefused(t *testing.T) {
	clientHome(t, "acme-box\n")
	var out, errOut bytes.Buffer
	code := Main([]string{"--client", "--bogus"}, &out, &errOut)
	if want := "ak attach: " + menuUsage + "  (got '--bogus')\n"; code != 2 || out.Len() != 0 || errOut.String() != want {
		t.Fatalf("exit=%d stdout=%q stderr=%q", code, out.String(), errOut.String())
	}
}

func TestSshNotStartingIsSaidWithItsReason(t *testing.T) {
	if runtime.GOOS == "darwin" {
		t.Skip("a Mac's real hop is Python's")
	}
	clientHome(t, "acme-box\n")
	t.Setenv("PATH", t.TempDir())
	var out, errOut bytes.Buffer
	code := Main(nil, &out, &errOut)
	if code != 2 || out.Len() != 0 || !strings.HasPrefix(errOut.String(), "ak attach: cannot run ssh: ") {
		t.Fatalf("exit=%d stdout=%q stderr=%q", code, out.String(), errOut.String())
	}
}

// TestAttachAsProgram is the program itself when a test below runs a copy of this binary, which
// is the only way to put os.Executable where a home's checkout would hold it.
func TestAttachAsProgram(t *testing.T) {
	if os.Getenv("AK_TEST_ATTACH") == "" {
		t.Skip("run by TestOnlyTheLiveCheckoutsOwnBuildLeavesTheHopToPython")
	}
	os.Exit(Main([]string{"--dry-run"}, os.Stdout, os.Stderr))
}

func TestOnlyTheLiveCheckoutsOwnBuildLeavesTheHopToPython(t *testing.T) {
	self, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	test, err := os.ReadFile(self)
	if err != nil {
		t.Fatal(err)
	}
	for _, place := range []struct {
		name, program string
		link          [2]string // a link at the first, relative to the home, to the second
		live          bool
	}{
		{name: "the live checkout", program: "agentkit/go/bin/ak", live: true},
		{name: "another file name there", program: "agentkit/go/bin/ak2", live: true},
		{name: "reached through a link", program: "src/acme/go/bin/ak", link: [2]string{"agentkit", "src/acme"}, live: true},
		{name: "a worktree nested inside it", program: "agentkit/wt/fix-api/go/bin/ak"},
		{name: "its other bin", program: "agentkit/bin/ak"},
		{name: "another checkout", program: "src/acme/go/bin/ak"},
	} {
		t.Run(place.name, func(t *testing.T) {
			home := clientHome(t, "acme-box\n")
			if place.link[0] != "" {
				if err := os.Symlink(filepath.Join(home, place.link[1]), filepath.Join(home, place.link[0])); err != nil {
					t.Fatal(err)
				}
			}
			program := filepath.Join(home, place.program)
			if err := os.MkdirAll(filepath.Dir(program), 0o700); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(program, test, 0o700); err != nil {
				t.Fatal(err)
			}
			run := exec.Command(program, "-test.run=^TestAttachAsProgram$")
			run.Env = append(os.Environ(), "AK_TEST_ATTACH=1")
			var out bytes.Buffer
			run.Stdout = &out
			run.Run() // how it ended is the exit code below, -1 if it never started
			code := run.ProcessState.ExitCode()
			if place.live && (code != 3 || out.Len() != 0) || !place.live && (code != 0 || out.String() != hopNamed) {
				t.Fatalf("exit=%d stdout=%q", code, out.String())
			}
		})
	}
}
