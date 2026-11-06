// Package install makes a home ready for Go's ak as install.sh does for Python's.  go/install.sh
// runs it as `ak install`, unlisted, so each step has one home here, the same on every system.
// So far it holds install.sh's options, its step (1), the seat guards, the role's record, the
// tick's crontab line and the install stamp; what else writes outside the home (packages,
// harnesses, a Mac's Linux machine) is still to come.
package install

import (
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"slices"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// serverName is the alias a client reaches when it names none, and the name a server goes by.
const serverName = "agentkit"

// Main is install.sh run with args: what it says, and its exit code.
func Main(args []string, out, errOut io.Writer) int {
	role, alias, refused := options(args)
	if refused != "" {
		fmt.Fprintln(errOut, "install.sh: "+refused)
		return 2
	}
	if role == "" {
		// a saved server elsewhere makes this a client; none, or one naming this host, a server
		saved, _ := os.ReadFile(filepath.Join(config.Home(), "state", "server"))
		alias, _, _ = strings.Cut(string(saved), "\n")
		role = "client"
		if alias == "" || serverBox(alias) {
			role = "server"
		}
	}
	if role == "client" && alias == "" {
		alias = serverName
	}
	sandboxed := sandbox()
	if role == "server" && runtime.GOOS == "darwin" && !sandboxed {
		// install.sh makes a Mac the client of a Linux machine of its own, the server
		fmt.Fprintln(errOut, "ak install: a Mac's server, a Linux machine of its own, is not set up in Go yet")
		return 3
	}
	if err := install(role, alias, sandboxed, out, errOut); err != nil {
		fmt.Fprintln(errOut, "install.sh:", err)
		return 1
	}
	return 0
}

// options are install.sh's: the role asked for ("" when none), a client's alias, and why
// they are refused.
func options(args []string) (role, alias, refused string) {
	for i := 0; i < len(args); i++ {
		switch args[i] {
		case "--server":
			role = "server"
		case "--client":
			role = "client"
			if i+1 < len(args) && !strings.HasPrefix(args[i+1], "-") {
				i++
				alias = args[i]
			}
		case "--link-doctrine", "--vm": // accepted for old callers, as install.sh accepts them
		case "--phone-key":
			if i+1 == len(args) {
				return "", "", "--phone-key needs a public key or a file"
			}
			i++ // the key is the phone key's step, which Go has yet to take over
		default:
			return "", "", "unknown option " + args[i] + " (expected --server, --client [ALIAS], --phone-key KEY|FILE)"
		}
	}
	return role, alias, ""
}

func install(role, alias string, sandboxed bool, out, errOut io.Writer) error {
	if role == "server" {
		fmt.Fprintln(out, "install mode: server")
	} else {
		fmt.Fprintln(out, "install mode: client of "+alias)
	}
	home, ak := config.UserHome(), config.Home()
	private := []string{ak, filepath.Join(ak, "state"), filepath.Join(ak, "secrets"), filepath.Join(ak, "tmp"), filepath.Join(ak, "env")}
	loop := []string{filepath.Join(ak, "runs"), filepath.Join(ak, "wt"), filepath.Join(ak, "work")}
	if role == "server" {
		private = append(private, loop...)
	} else if kept := loopKept(ak); kept != "" {
		fmt.Fprintln(errOut, "note: local loop state kept: "+kept)
	} else {
		// the server's loop alone, its links not followed: the record, credentials and the
		// rest of this host's own state stay
		for _, dir := range loop {
			if err := os.RemoveAll(dir); err != nil {
				return err
			}
		}
	}
	for _, dir := range private {
		if err := os.MkdirAll(dir, 0o700); err != nil {
			return err
		}
		if err := os.Chmod(dir, 0o700); err != nil {
			return err
		}
	}
	// A seat started before ak stopped compacting seats types `/compact` once a stamp here is
	// old enough; nothing writes one any more, and every install takes away those left.
	for _, stamp := range config.Glob(filepath.Join(ak, "state", "idle-compact"), "*.json") {
		os.Remove(stamp)
	}
	// The shipped default is copied only where there is no config: what the owner wrote stays.
	owned := filepath.Join(ak, "config.toml")
	if _, err := os.Stat(owned); err != nil {
		// O_EXCL: a dangling link here is refused, as cp refuses it, never written through
		file, err := os.OpenFile(owned, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
		if errors.Is(err, os.ErrExist) {
			return fmt.Errorf("not writing through %s, a link to nothing", owned)
		}
		if err != nil {
			return err
		}
		_, err = file.WriteString(config.Shipped())
		if err := errors.Join(err, file.Chmod(0o600), file.Close()); err != nil {
			return err
		}
		fmt.Fprintf(out, "wrote %s from config.default.toml; it is yours to edit from here on\n", owned)
	}
	if err := onPath(role, home, out); err != nil {
		return err
	}
	if err := guards(); err != nil {
		fmt.Fprintf(errOut, "note: the seat guards in %s were not linked (%v); the next seat started links them\n", filepath.Join(ak, "bin"), err)
	}
	record := filepath.Join(ak, "state", "server")
	if role == "client" {
		fmt.Fprintf(out, "client: the server is `ssh %s`; `ak` runs the menu there\n", alias)
		return os.WriteFile(record, []byte(alias+"\n"), 0o600)
	}
	if err := os.Remove(record); err != nil && !os.IsNotExist(err) {
		return err
	}
	if err := cron(sandboxed, out, errOut); err != nil {
		return err
	}
	stamp := filepath.Join(ak, "state", "installed-at")
	if _, err := os.Stat(stamp); err == nil {
		return nil
	}
	return os.WriteFile(stamp, []byte(fmt.Sprintf("%d\n", time.Now().Unix())), 0o600)
}

// onPath puts ak on PATH: ~/.local/bin/ak, a link to this program, and the line that puts that
// folder first, above the early return of a non-interactive bashrc, which is all `ssh host ak`
// reads.  Of the per-command links earlier versions left there, only those that were ak's go.
func onPath(role, home string, out io.Writer) error {
	executable, err := os.Executable()
	if err != nil {
		return err
	}
	program := config.Resolve(executable)
	checkout := filepath.Dir(filepath.Dir(program))
	bin := filepath.Join(home, ".local", "bin")
	if err := os.MkdirAll(bin, 0o700); err != nil {
		return err
	}
	if role == "server" {
		if err := os.MkdirAll(filepath.Join(home, "code"), 0o700); err != nil { // where seats open
			return err
		}
	}
	link := filepath.Join(bin, "ak")
	os.Remove(link)
	if err := os.Symlink(program, link); err != nil {
		return err
	}
	here, _ := os.Stat(bin)
	for _, name := range []string{"usage", "worker", "run", "notify", "orch", "__pycache__"} {
		stale := filepath.Join(bin, name)
		target, err := os.Readlink(stale)
		if err != nil {
			continue
		}
		// ak's if it names this checkout's, or a bin/ that holds ak, or dangles at a */bin/<name>.
		// The folder is where the link points, wherever install runs from, and never this one:
		// the ak link just made here says nothing of the owner's tools beside it.
		folder := filepath.Dir(target)
		if !filepath.IsAbs(target) {
			folder = filepath.Dir(filepath.Join(bin, target))
		}
		there, err := os.Stat(folder)
		_, holds := os.Stat(filepath.Join(folder, "ak"))
		beside := err == nil && holds == nil && !os.SameFile(there, here)
		_, dangles := os.Stat(stale)
		if target == filepath.Join(checkout, "bin", name) || beside ||
			dangles != nil && strings.HasSuffix(target, "/bin/"+name) {
			os.Remove(stale)
			fmt.Fprintf(out, "removed stale symlink %s -> %s\n", stale, target)
		}
	}
	fmt.Fprintf(out, "installed: %s (0700) and %s -> %s\n", config.Home(), link, program)
	rcs := []string{".bashrc", ".profile"}
	if runtime.GOOS == "darwin" {
		rcs = []string{".zshrc", ".zprofile"}
	}
	for _, name := range rcs {
		rc := filepath.Join(home, name)
		text, err := os.ReadFile(rc)
		if err != nil && !os.IsNotExist(err) {
			return err
		}
		if strings.Contains(string(text), "agentkit PATH") {
			continue
		}
		line := "# agentkit PATH (kept above bashrc non-interactive early return)\n" +
			`export PATH="$HOME/.local/bin:$HOME/.npm-global/bin:$PATH"` + "\n\n"
		if err := os.WriteFile(rc, append([]byte(line), text...), 0o600); err != nil {
			return err
		}
		fmt.Fprintf(out, "PATH line prepended to %s\n", rc)
	}
	return nil
}

// loopKept is why a client keeps the server's loop state found here, "" where it goes: a
// mistaken --client, or a tailnet that cannot say who this is, must not erase unfinished work.
func loopKept(ak string) string {
	if serverBox(serverName) {
		return "this host identifies as " + serverName + "; inspect it on the server before removing it"
	}
	const unfinished = "unfinished or unreadable runs; inspect them on the server before removing them"
	runs := filepath.Join(ak, "runs")
	if info, err := os.Stat(runs); err != nil || !info.IsDir() {
		return ""
	}
	entries, err := os.ReadDir(runs)
	if err != nil {
		return unfinished
	}
	for _, entry := range entries {
		dir := filepath.Join(runs, entry.Name())
		info, err := os.Stat(dir)
		if err != nil && !os.IsNotExist(err) {
			return unfinished // could not be looked at: unverified work
		}
		if err != nil || !info.IsDir() {
			continue
		}
		record, _ := run.Read(dir)
		if record == nil || !record.Truthy("finished_at") || record.Truthy("recovery_pending") ||
			slices.Contains([]string{"queued", "running", "interrupted"}, record.Str("state")) {
			return unfinished
		}
	}
	return ""
}

var tailnetName = regexp.MustCompile(`"HostName":[[:space:]]*"([^"]*)"`)

// serverBox is whether this host is the server called name: by its short host name, or by its
// own name on the tailnet (--peers=false, so a peer of that name never makes this the server).
func serverBox(name string) bool {
	short, err := exec.Command("hostname", "-s").Output()
	if err != nil {
		short, _ = exec.Command("hostname").Output()
	}
	if strings.TrimRight(string(short), "\n") == name {
		return true
	}
	said, err := exec.Command("tailscale", "status", "--peers=false", "--json").Output()
	if err != nil {
		return false
	}
	for _, found := range tailnetName.FindAllSubmatch(said, -1) {
		if string(found[1]) == name {
			return true
		}
	}
	return false
}
