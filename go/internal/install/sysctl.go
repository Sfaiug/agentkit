package install

import (
	"cmp"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path"
	"path/filepath"
	"strconv"
	"strings"
)

// coreDumps leaves a crashed program no core dump file, as install.sh's step of that name does.
// The kernel's default pattern, `core`, writes a crashed process's whole memory into its working
// directory wherever its limit allows one, and a container's processes run under the container
// daemon's, which allows any size: crashing browser tests once left 39 GiB in a seat's scratch
// folder.  Nobody reads one: a crash is chased from what the program printed.  A live pattern
// starting with `|` hands dumps to a program, a collector the owner set up or ours, and is left
// as it is; any other becomes ours, which discards them, now and on every boot.
func coreDumps(out, errOut io.Writer) {
	live := cmp.Or(os.Getenv("AK_CORE_PATTERN"), "/proc/sys/kernel/core_pattern")
	now, err := os.ReadFile(live)
	switch {
	case err != nil || strings.HasPrefix(string(now), "|"):
		// a host with no pattern to read (a Mac) has none to set
	case !passwordless():
		fmt.Fprintln(errOut, "note: core dumps: no passwordless sudo, so kernel.core_pattern is not set to discard them; run `sudo -v` and re-run ./install.sh")
	case sysctlSet(live, "kernel.core_pattern", "|/bin/false", "no-core-dumps", "a crashed program leaves no core dump file"):
		fmt.Fprintln(out, "core dumps: a crashed program leaves none, now and on every boot")
	default:
		fmt.Fprintln(errOut, "note: core dumps: kernel.core_pattern could not be set; see "+sysctlD())
	}
}

// inotify leaves every session room for its inotify instances, as install.sh's step of that name
// does.  Each harness process holds an inotify instance or two, and the kernel allows one user 128
// whatever the host's size: 30 seats and 33 runs once held 99, and past the limit a harness's
// file watching fails, as a test opening its own did at landing.  An instance costs kernel
// memory only while it is open, so a floor of 8192 costs a host nothing, and a host that allows
// more keeps its own.
func inotify(out, errOut io.Writer) {
	const floor = 8192
	live := cmp.Or(os.Getenv("AK_INOTIFY_INSTANCES"), "/proc/sys/fs/inotify/max_user_instances")
	read, err := os.ReadFile(live)
	now := strings.TrimSpace(string(read))
	limit, _ := strconv.Atoi(now)
	switch {
	case err != nil || limit >= floor:
		// a host with no limit to read (a Mac) has none to set
	case !passwordless():
		fmt.Fprintln(errOut, "note: inotify: no passwordless sudo, so fs.inotify.max_user_instances stays "+now+"; run `sudo -v` and re-run ./install.sh")
	case sysctlSet(live, "fs.inotify.max_user_instances", strconv.Itoa(floor), "inotify", "every session has room for its inotify instances"):
		fmt.Fprintf(out, "inotify: room for %d instances per user, now and on every boot\n", floor)
	default:
		fmt.Fprintln(errOut, "note: inotify: fs.inotify.max_user_instances could not be set; see "+sysctlD())
	}
}

// sysctlD is where systemd-sysctl finds the entries it applies at boot.
func sysctlD() string { return cmp.Or(os.Getenv("AK_SYSCTL_D"), "/etc/sysctl.d") }

// sysctlSet sets key to value on every boot, through ak's entry for name in sysctl.d in place of
// an earlier install's, then now, in the live file: the entry first, as the live value alone
// decides whether an install writes it, and once that is ours none does.  Whether both are set.
func sysctlSet(live, key, value, name, why string) bool {
	dir, ours := sysctlD(), "-agentkit-"+name+".conf"
	// listed and measured through sudo, as written, so an entry only root can reach still sorts
	// before ours
	if _, err := sudo("mkdir", "-p", "--", dir); err != nil {
		return false
	}
	listed, err := sudo("ls", "--", dir)
	if err != nil {
		return false
	}
	most, err := sudo("getconf", "NAME_MAX", dir)
	if err != nil {
		return false
	}
	fit, err := strconv.Atoi(strings.TrimSpace(most))
	if err != nil {
		return false
	}
	fit -= len(ours)
	// systemd-sysctl applies entries in the byte order of their names, the last value for a key
	// winning, and a name extended sorts after it: ours is the last of `zz` and every other name
	// (99-sysctl.conf, which is /etc/sysctl.conf, included), extended, so it is applied last.
	// Only that rule makes these two shapes, but a name proves nothing: an entry of either is ak's
	// only if it is a file whose bytes open with the line every release has written first into
	// each (a pipe is never opened), and an owner's is followed like any other.  ak's own under
	// this name is an earlier install's, removed once ours is written, so a write that fails leaves
	// every boot the setting that worked; under another it is another key's, followed only if it
	// holds this key's last part, which every spelling of the key does, so one this key was added
	// to still applies first and neither of ak's names grows out of the other's.
	last := "zz"
	var earlier []string
	for _, entry := range strings.Split(listed, "\n") {
		shaped := func(patterns ...string) bool {
			for _, pattern := range patterns {
				if matched, _ := path.Match(pattern, entry); matched {
					return true
				}
			}
			return false
		}
		switch file := filepath.Join(dir, entry); {
		case shaped("zz"+ours, "*.conf"+ours) && akWrote(file):
			earlier = append(earlier, entry)
		case shaped("zz-agentkit-*.conf", "*.conf-agentkit-*.conf") && akWrote(file):
			if _, err := sudo("grep", "-qF", "--", key[strings.LastIndex(key, ".")+1:], file); err == nil {
				last = max(last, entry)
			}
		case shaped("*.conf"):
			last = max(last, entry)
		}
	}
	// one too long to extend within the filesystem's limit gives way to a .conf name that fits:
	// cut, then until ours sorts after it, a last 0xff dropped or a last byte raised (past `/`,
	// which no name holds)
	if len(last) > fit {
		cut := []byte(last[:max(fit-5, 0)])
		for string(cut)+".conf"+ours <= last {
			switch end := len(cut) - 1; {
			case end < 0:
				return false
			case cut[end] == 0xff:
				cut = cut[:end]
			default:
				if cut[end]++; cut[end] == '/' {
					cut[end]++
				}
			}
		}
		last = string(cut) + ".conf"
	}
	if !written(filepath.Join(dir, last+ours), mark+": "+why+"\n"+key+" = "+value+"\n") {
		return false
	}
	for _, entry := range earlier {
		if entry == last+ours {
			continue // the name just written holds ours now
		}
		if _, err := sudo("rm", "-f", "--", filepath.Join(dir, entry)); err != nil {
			return false
		}
	}
	return written(live, value)
}

// mark opens every sysctl.d entry ak has written, in every release.
const mark = "# Written by agentkit's install.sh"

// akWrote is whether file, read as root, is a regular file whose bytes open with mark.
func akWrote(file string) bool {
	if _, err := sudo("test", "-f", file); err != nil {
		return false
	}
	head, err := sudo("head", "-c", strconv.Itoa(len(mark)), "--", file)
	return err == nil && head == mark
}

// passwordless is whether sudo runs a command as root without asking for a password.
func passwordless() bool {
	_, err := sudo("true")
	return err == nil
}

// sudo is what args run as root say, never asking for a password.
func sudo(args ...string) (string, error) {
	said, err := exec.Command("sudo", append([]string{"-n"}, args...)...).Output()
	return string(said), err
}

// written is whether text was written into file as root.
func written(file, text string) bool {
	tee := exec.Command("sudo", "-n", "tee", file)
	tee.Stdin = strings.NewReader(text)
	return tee.Run() == nil
}
