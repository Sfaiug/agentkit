// Package leftover ends what a gone `ak` or helper left running in its session, and what a seat
// ak has forgotten left running anywhere, Python's owner.leftovers and owner.sweep: Sweep. It
// hides the look at /proc, the mark's format (host.Mark writes it), which processes are never
// ended, the grace between TERM and KILL, and the hold on each process a signal goes to. Without
// /proc it finds nothing.
package leftover

import (
	"maps"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"agentkit/internal/commandhelp"
	"agentkit/internal/host"
	"agentkit/internal/seat"
)

const server = "tmux: server\n" // what tmux names its server process, in its comm

var (
	proc  = "/proc"
	grace = 5 * time.Second // a leftover sent TERM has this long to end before the second look KILLs it
	send  = signal
	mark  = regexp.MustCompile(`^(\d+) (\d+) (\d+) (\d+) (.+)$`)
)

// forgotten is the question whether ak has forgotten a seat (Home.Forgotten), asked of the home as
// the tick reads it now (seat.TickHome), every seat tmux holds, a legacy one too, among it; false
// where Go does not read that home.
var forgotten = func() (func(tag string) bool, bool) {
	home, known := seat.TickHome(time.Now())
	return home.Forgotten, known
}

// Sweep is TERM to each leftover a look finds and, only where one went, KILL a grace later to
// each a second look finds, each logged. Each look starts from scratch, so one that has become a
// process the sweep never ends meanwhile, or whose seat is back, gets no KILL. False where a look
// finds a seat's tag on a home Go does not read, before it signals anything: what the first look
// sent stands, and Python's next sweep finds it done.
func Sweep(log func(string)) bool {
	sent, known := signalAll(syscall.SIGTERM, "TERM", log)
	if sent {
		time.Sleep(grace)
		_, known = signalAll(syscall.SIGKILL, "KILL", log)
	}
	return known
}

// A found process is one a look finds: its pid with its start, its command's words and whose it is.
type found struct {
	pid   int
	start int64
	words []string
	whose string
}

func signalAll(number syscall.Signal, name string, log func(string)) (sent, known bool) {
	leftovers, known := look()
	for _, each := range leftovers {
		if send(each.pid, each.start, number) {
			log(name + " to " + commandhelp.ShellJoin(each.words) + " (pid " + strconv.Itoa(each.pid) + "), " + each.whose)
			sent = true
		}
	}
	return sent, known
}

// look is each leftover, by pid, those a gone `ak` or helper left first. Such a one's mark names
// this pid namespace and its own session, as what left for a session of its own is a service
// someone started on purpose; it is no tmux server nor below one, whose pids are not ours; and the
// mark's pid names no process, an exited one, or one with another start. Any other carries the tag
// (AK_TMUX_OWNER) of a seat ak has forgotten, wherever it runs, which is asked once a look of each
// tag, of a home read only where a tag is there to ask about; false where Go does not read it.
// Never one that exited, of a run, a tmux server, or another HOME's.
func look() ([]found, bool) {
	entries, err := os.ReadDir(proc)
	if err != nil {
		return nil, true
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
	var leftovers, seats []found
	asking := sync.OnceValues(forgotten)
	gone := map[string]bool{} // each tag asked about, and whether ak has forgotten its seat
	for _, pid := range pids {
		stat, env := stats[pid], environ(pid)
		owner, tag := mark.FindStringSubmatch(env["AK_OWNER"]), env["AK_TMUX_OWNER"]
		theirs, theirsSet := env["HOME"]
		_, ofRun := env[host.Marker]
		if owner == nil && tag == "" || stat.Exited() || ofRun || theirs != home || theirsSet != homed || read(pid, "comm") == server {
			continue
		}
		words := slices.DeleteFunc(strings.Split(read(pid, "cmdline"), "\x00"), func(word string) bool { return word == "" })
		if owner != nil && named && number(owner[1]) == namespace && number(owner[4]) == int64(stat.Session) && !underTmux(pid, stats) {
			if was, ok := stats[int(number(owner[2]))]; !ok || was.Exited() || was.Start != number(owner[3]) {
				leftovers = append(leftovers, found{pid, stat.Start, words,
					"which a gone `" + owner[5] + "` (pid " + owner[2] + ") left running"})
				continue
			}
		}
		if tag == "" {
			continue
		}
		ask, known := asking()
		if !known {
			return nil, false
		}
		if _, asked := gone[tag]; !asked {
			gone[tag] = ask(tag)
		}
		if gone[tag] {
			seats = append(seats, found{pid, stat.Start, words, "which a forgotten seat `" + tag + "` left running"})
		}
	}
	return append(leftovers, seats...), true
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
