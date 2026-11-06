package install

import (
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"sync"

	"agentkit/internal/config"
)

// A Mac's server is a Linux machine of ak's own on it, as tools/linux-machine.sh sets it up: ak's
// worker box, landing gate and limits exist only on Linux.  Lima (2.2 or newer, for `limactl
// autostart`) runs it on Apple's virtualization, and the Mac reaches it as machineAlias, a local
// port that needs no network.
const (
	machineName  = "ak"
	machineAlias = "lima-" + machineName
)

// mac is whether this host is a Mac, as install.sh reads it: by `uname -s`.
var mac = sync.OnceValue(func() bool {
	said, _ := exec.Command("uname", "-s").Output()
	return strings.TrimSpace(string(said)) == "Darwin"
})

// linuxMachine makes sure this Mac's Linux machine is up, stays up with the Mac and has ak's
// server installed in it, as install.sh's step (2b) does; nothing already right changes.
func linuxMachine(out, errOut io.Writer) error {
	// The Mac account's own name and /home/<name>, Lima's default being /home/<name>.linux: a
	// server moved in from a Linux VM with the same user keeps the absolute paths its run
	// records hold.
	name := os.Getenv("USER")
	if name == "" {
		said, _ := exec.Command("id", "-un").Output()
		name = strings.TrimSpace(string(said))
	}
	if err := machineUp(name, out, errOut); err != nil {
		return fmt.Errorf("this Mac's Linux machine is not up (%w); see above, then run ./install.sh again", err)
	}
	// `limactl shell` puts a terminal on the command when its stdin is one
	inside := func(args ...string) *exec.Cmd {
		command := exec.Command("limactl", append([]string{"shell", "--workdir", "/home/" + name, machineName}, args...)...)
		command.Stdin, command.Stdout, command.Stderr = os.Stdin, out, errOut
		return command
	}
	if inside("test", "-e", "agentkit/.git").Run() != nil {
		if err := carry(inside, out, errOut); err != nil {
			return fmt.Errorf("ak was not copied into this Mac's Linux machine (%w); run ./install.sh again", err)
		}
	}
	// Failing here records no server, so the next install sets the machine up again.
	if inside("bash", "agentkit/install.sh", "--server").Run() != nil {
		return errors.New("the server install in this Mac's Linux machine did not finish; run ./install.sh again")
	}
	return nil
}

// machineUp is tools/linux-machine.sh's linux_machine_up: the machine exists, is up and stays up
// with the Mac, and ssh reaches it.
func machineUp(name string, out, errOut io.Writer) error {
	lima := os.Getenv("LIMA_HOME")
	if lima == "" {
		lima = filepath.Join(config.UserHome(), ".lima")
	}
	dir := filepath.Join(lima, machineName)
	if exec.Command("limactl", "autostart", "--help").Run() != nil {
		verb := "install"
		if _, err := exec.LookPath("limactl"); err == nil {
			verb = "upgrade"
		}
		if err := tool(out, errOut, "brew", verb, "lima"); err != nil {
			return err
		}
	}
	if _, err := os.Stat(filepath.Join(dir, "lima.yaml")); err != nil {
		// Cores are shared with macOS as it runs, so a quarter left to it is room to schedule.
		// Memory is a reservation: the Mac never gets back what the machine has once touched.
		// The disk grows as it fills and never shrinks, so it is a share of the space free now.
		cores, coresErr := reading(0, 0, "sysctl", "-n", "hw.ncpu")
		memory, memoryErr := reading(0, 0, "sysctl", "-n", "hw.memsize")
		free, freeErr := reading(1, 3, "df", "-Pk", config.UserHome())
		if err := errors.Join(coresErr, memoryErr, freeErr); err != nil {
			return err
		}
		cpus, mem, disk := share(cores, 2), share(memory>>30, 4), share(free>>20, 64) // bytes and KiB, in GiB
		// Debian stable, which boots systemd; --mount-none: the machine sees none of the Mac's folders
		if err := tool(out, errOut, "limactl", "create", "--tty=false", "--name="+machineName,
			fmt.Sprintf("--cpus=%d", cpus), fmt.Sprintf("--memory=%d", mem), fmt.Sprintf("--disk=%d", disk),
			"--mount-none", "--set", fmt.Sprintf(".user.name = %q | .user.home = %q", name, "/home/"+name),
			"template:debian"); err != nil {
			return err
		}
		fmt.Fprintf(out, "linux: this Mac's Linux machine has %d cores, %d GiB of memory and %d GiB of disk\n", cpus, mem, disk)
	}
	if err := tool(out, errOut, "limactl", "start", "--tty=false", machineName); err != nil { // one up stays as it is
		return err
	}
	// A system LaunchDaemon starts it with the Mac, before anyone logs in; enabling asks for sudo.
	daemons := os.Getenv("AK_LAUNCH_DAEMONS")
	if daemons == "" {
		daemons = "/Library/LaunchDaemons"
	}
	if _, err := os.Stat(filepath.Join(daemons, "io.lima-vm.daemon."+machineName+".plist")); err != nil {
		if err := tool(out, errOut, "limactl", "autostart", "enable", "--condition=boot", machineName); err != nil {
			return err
		}
		fmt.Fprintln(out, "linux: this Mac's Linux machine starts when the Mac does")
	}
	if err := awake(out, errOut); err != nil {
		return err
	}
	// FileVault holds a Mac that starts again at its password before anything of it runs.
	if exec.Command("fdesetup", "isactive").Run() == nil {
		fmt.Fprintln(out, "power: FileVault is on, so after a restart this Mac waits for its password, and ak's machine stays down until someone enters it")
	}
	return reachable(dir, out)
}

// awake keeps the Mac up for its machine: on power it never sleeps, though its display may, and
// it starts again by itself when power comes back after a cut.  pmset keeps both across
// restarts; only what is not so yet is set, which asks for sudo as the start at boot does.
func awake(out, errOut io.Writer) error {
	said, err := exec.Command("pmset", "-g", "custom").Output()
	if err != nil {
		return fmt.Errorf("pmset -g custom: %w", err)
	}
	wanted := map[string]string{"sleep": "0", "autorestart": "1"}
	settings, ac := []string{"-c"}, false
	for _, line := range strings.Split(string(said), "\n") {
		if line != "" && line[0] != ' ' { // a power source's name; its settings are indented
			ac = strings.HasPrefix(line, "AC Power:")
		}
		words := strings.Fields(line)
		if ac && len(words) > 1 && wanted[words[0]] != "" && words[1] != wanted[words[0]] {
			settings = append(settings, words[0], wanted[words[0]])
		}
	}
	if len(settings) == 1 {
		return nil
	}
	if err := tool(out, errOut, "sudo", append([]string{"pmset"}, settings...)...); err != nil {
		return err
	}
	fmt.Fprintln(out, "power: this Mac never sleeps on power, though its display may, and starts again after a power cut")
	return nil
}

// reachable lets ssh reach the machine as machineAlias: Lima keeps the alias's port and key in
// its own ssh.config, which ssh reads through an Include first in ~/.ssh/config, where it holds
// for every host.
func reachable(dir string, out io.Writer) error {
	ssh := filepath.Join(config.UserHome(), ".ssh")
	path, include := filepath.Join(ssh, "config"), "Include "+filepath.Join(dir, "ssh.config")
	text, err := os.ReadFile(path)
	if err != nil && !os.IsNotExist(err) {
		return err
	}
	if slices.Contains(strings.Split(string(text), "\n"), include) {
		return nil
	}
	if err := errors.Join(os.MkdirAll(ssh, 0o700), os.Chmod(ssh, 0o700)); err != nil {
		return err
	}
	if err := errors.Join(os.WriteFile(path, append([]byte(include+"\n"), text...), 0o600), os.Chmod(path, 0o600)); err != nil {
		return err
	}
	fmt.Fprintf(out, "ssh: `ssh %s` reaches this Mac's Linux machine\n", machineAlias)
	return nil
}

// carry gives a new machine this checkout's commit from the Mac, so it needs no login to fetch
// it: a clone, and not the checkout, so that nothing uncommitted goes and git need not be there
// yet.  From then on its checkout is the server's own, which its tick keeps at origin/main, its
// .git a file once a version is swapped in.
func carry(inside func(...string) *exec.Cmd, out, errOut io.Writer) error {
	repo := config.Repo()
	tmp, err := os.MkdirTemp("", "ak-machine-")
	if err != nil {
		return err
	}
	defer os.RemoveAll(tmp)
	clone, archive := filepath.Join(tmp, "agentkit"), filepath.Join(tmp, "agentkit.tar")
	if err := tool(out, errOut, "git", "clone", "-q", "--depth", "1", "--", "file://"+repo, clone); err != nil {
		return err
	}
	// the checkout's origin, or none where it has none: the machine cannot reach the Mac's path
	said, _ := exec.Command("git", "-C", repo, "remote", "get-url", "origin").Output()
	origin := []string{"remove", "origin"}
	if url := strings.TrimSpace(string(said)); url != "" {
		origin = []string{"set-url", "origin", url}
	}
	if err := tool(out, errOut, "git", append([]string{"-C", clone, "remote"}, origin...)...); err != nil {
		return err
	}
	if err := tool(out, errOut, "tar", "-C", clone, "-cf", archive, "."); err != nil {
		return err
	}
	file, err := os.Open(archive)
	if err != nil {
		return err
	}
	defer file.Close()
	unpack := inside("sh", "-c", "mkdir -p agentkit && tar -xf - -C agentkit")
	unpack.Stdin = file
	if err := unpack.Run(); err != nil {
		return err
	}
	short, _ := exec.Command("git", "-C", repo, "rev-parse", "--short", "HEAD").Output()
	fmt.Fprintf(out, "linux: ak %s copied into this Mac's Linux machine\n", strings.TrimSpace(string(short)))
	return nil
}

// share is what the machine takes of the Mac's total: macOS keeps a quarter for the desktop and
// its renders, and never less than floor until that would be more than half, so a small Mac
// still lends the machine half of what it has.
func share(total, floor int64) int64 {
	return total - max(total/4, min(floor, total/2))
}

// reading is the whole number a host tool prints as the word'th word of its line'th line,
// counting from 0.
func reading(line, word int, name string, args ...string) (int64, error) {
	said, err := exec.Command(name, args...).Output()
	if err != nil {
		return 0, fmt.Errorf("%s: %w", name, err)
	}
	if lines := strings.Split(string(said), "\n"); line < len(lines) {
		if words := strings.Fields(lines[line]); word < len(words) {
			if number, err := strconv.ParseInt(words[word], 10, 64); err == nil {
				return number, nil
			}
		}
	}
	return 0, fmt.Errorf("%s %s said no number: %q", name, strings.Join(args, " "), said)
}

// tool runs a host tool on the install's own terminal, as install.sh runs one: it may ask, as
// sudo does, and what it says is the install's.
func tool(out, errOut io.Writer, name string, args ...string) error {
	command := exec.Command(name, args...)
	command.Stdin, command.Stdout, command.Stderr = os.Stdin, out, errOut
	if err := command.Run(); err != nil {
		return fmt.Errorf("%s: %w", strings.Join(command.Args, " "), err)
	}
	return nil
}
