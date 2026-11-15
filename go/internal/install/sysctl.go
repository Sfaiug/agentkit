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
	case exec.Command("sudo", "-n", "true").Run() != nil:
		fmt.Fprintln(errOut, "note: core dumps: no passwordless sudo, so kernel.core_pattern is not set to discard them; run `sudo -v` and re-run ./install.sh")
	case sysctlSet(live, "kernel.core_pattern", "|/bin/false", "no-core-dumps", "a crashed program leaves no core dump file"):
		fmt.Fprintln(out, "core dumps: a crashed program leaves none, now and on every boot")
	default:
		fmt.Fprintln(errOut, "note: core dumps: kernel.core_pattern could not be set; see "+sysctlD())
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
	// Only that rule makes these two shapes, so an entry of either is an earlier install's.  ak's
	// entries for other keys take them with their own names, and ours follows such a name only if
	// it holds this key's last part, which every spelling of the key does, so an owner's entry
	// named like ak's is still followed and neither of ak's names grows out of the other's.
	last := "zz"
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
		case shaped("zz"+ours, "*.conf"+ours):
			if _, err := sudo("rm", "-f", "--", file); err != nil {
				return false
			}
		case shaped("zz-agentkit-*.conf", "*.conf-agentkit-*.conf"):
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
	return written(filepath.Join(dir, last+ours), "# Written by agentkit's install.sh: "+why+"\n"+key+" = "+value+"\n") &&
		written(live, value)
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
