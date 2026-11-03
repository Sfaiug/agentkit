// Package leftover ends what a gone `ak` or helper left running in its session, Python's
// owner.leftovers and owner.sweep: Sweep, and Tagless for what only Python tells. It hides the
// look at /proc, the mark's format (host.Mark writes it), which processes are never ended, the
// grace between TERM and KILL, and the hold on each process a signal goes to. Without /proc
// it finds nothing.
package leftover

import (
	"maps"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"syscall"
	"time"

	"agentkit/internal/commandhelp"
	"agentkit/internal/host"
)

const server = "tmux: server\n" // what tmux names its server process, in its comm

var (
	proc  = "/proc"
	grace = 5 * time.Second // a leftover sent TERM has this long to end before the second look KILLs it
	send  = signal
	mark  = regexp.MustCompile(`^(\d+) (\d+) (\d+) (\d+) (.+)$`)
)

// Sweep is TERM to each leftover a look finds and, only where one went, KILL a grace later to
// each a second look finds, each logged. Each look starts from scratch, so one that has become a
// process the sweep never ends meanwhile gets no KILL.
func Sweep(log func(string)) {
	if signalAll(syscall.SIGTERM, "TERM", log) {
		time.Sleep(grace)
		signalAll(syscall.SIGKILL, "KILL", log)
	}
}

// Tagless is whether no process the sweep may end carries a seat's tag (AK_TMUX_OWNER): only
// Python tells whether it names a seat ak has forgotten.
func Tagless() bool {
	_, tagged := look()
	return !tagged
}

// A found process is one a look finds: its pid with its start, its command's words and whose it is.
type found struct {
	pid   int
	start int64
	words []string
	whose string
}

func signalAll(number syscall.Signal, name string, log func(string)) bool {
	leftovers, _ := look()
	sent := false
	for _, each := range leftovers {
		if send(each.pid, each.start, number) {
			log(name + " to " + commandhelp.ShellJoin(each.words) + " (pid " + strconv.Itoa(each.pid) + "), " + each.whose)
			sent = true
		}
	}
	return sent
}

// look is each leftover, by pid, and whether a process the sweep may end carries a seat's tag. A
// leftover's mark names this pid namespace and its own session, as what left for a session of
// its own is a service someone started on purpose; it is no tmux server nor below one, whose
// pids are not ours; and the mark's pid names no process, an exited one, or one with another
// start. Never one that exited, of a run, a tmux server, or another HOME's.
func look() ([]found, bool) {
	entries, err := os.ReadDir(proc)
	if err != nil {
		return nil, false
	}
	link, _ := os.Readlink(filepath.Join(proc, "self", "ns", "pid")) // `pid:[<inode>]`
	inode, named := strings.CutPrefix(strings.TrimSuffix(link, "]"), "pid:[")
	namespace := number(inode)
	stats := map[int]host.Stat{}
	for _, entry := range entries {
		if pid, err := strconv.Atoi(entry.Name()); err == nil {
			if stat, ok := readStat(pid); ok {
				stats[pid] = stat
			}
		}
	}
	pids := slices.Sorted(maps.Keys(stats))
	home, homed := os.LookupEnv("HOME")
	var leftovers []found
	tagged := false
	for _, pid := range pids {
		stat, env := stats[pid], environ(pid)
		owner, tag := mark.FindStringSubmatch(env["AK_OWNER"]), env["AK_TMUX_OWNER"] != ""
		theirs, theirsSet := env["HOME"]
		_, ofRun := env[host.Marker]
		if owner == nil && !tag || stat.Exited() || ofRun || theirs != home || theirsSet != homed || read(pid, "comm") == server {
			continue
		}
		if owner != nil && named && number(owner[1]) == namespace && number(owner[4]) == int64(stat.Session) && !underTmux(pid, stats) {
			if was, ok := stats[int(number(owner[2]))]; !ok || was.Exited() || was.Start != number(owner[3]) {
				words := slices.DeleteFunc(strings.Split(read(pid, "cmdline"), "\x00"), func(word string) bool { return word == "" })
				leftovers = append(leftovers, found{pid, stat.Start, words,
					"which a gone `" + owner[5] + "` (pid " + owner[2] + ") left running"})
				continue
			}
		}
		tagged = tagged || tag
	}
	return leftovers, tagged
}

// number is a mark's or a link's number, or -1, which names no pid, start, session or namespace.
func number(text string) int64 {
	value, err := strconv.ParseInt(text, 10, 64)
	if err != nil {
		return -1
	}
	return value
}

// underTmux is whether that process is a tmux server, by its comm, or below one. stats is read a
// process at a time, so a pid given anew between two reads can close a loop of parents: the walk
// ends where it would come back.
func underTmux(pid int, stats map[int]host.Stat) bool {
	seen := map[int]bool{}
	for stat, ok := stats[pid]; ok && !seen[pid]; stat, ok = stats[pid] {
		if read(pid, "comm") == server {
			return true
		}
		seen[pid] = true
		pid = stat.Parent
	}
	return false
}

// signal sends number to the process at pid only if it started at start: os.FindProcess holds
// it by a pidfd, as Python's pidfd_open does, and while the pid names one with that start, the
// held one is it.
func signal(pid int, start int64, number syscall.Signal) bool {
	held, err := os.FindProcess(pid)
	if err != nil {
		return false
	}
	defer held.Release()
	if stat, ok := readStat(pid); !ok || stat.Start != start {
		return false
	}
	return held.Signal(number) == nil
}

func readStat(pid int) (host.Stat, bool) { return host.ReadStatIn(proc, pid) }

// environ is that process's environment as it was started, by name, a later one of a name
// winning as in Python's dict; empty where it cannot be read.
func environ(pid int) map[string]string {
	env := map[string]string{}
	for _, pair := range strings.Split(read(pid, "environ"), "\x00") {
		if name, value, ok := strings.Cut(pair, "="); ok {
			env[name] = value
		}
	}
	return env
}

// read is that file of the process in /proc; empty where it cannot be read.
func read(pid int, name string) string {
	data, _ := os.ReadFile(filepath.Join(proc, strconv.Itoa(pid), name))
	return string(data)
}
