package run

import (
	"os"
	"path/filepath"
	"slices"
	"strconv"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/host"
)

// ResumeArgs are the run and the rounds `ak run resume` is given, Python's run.resume_args:
// `<id> [--rounds N] [--bg]`, its rounds "" where none are asked, false where they are not that.
func ResumeArgs(args []string) (id, rounds string, ok bool) {
	args = slices.DeleteFunc(slices.Clone(args), func(arg string) bool { return arg == "--bg" })
	if len(args) == 3 && args[1] == "--rounds" && config.Digits(args[2]) && strings.TrimLeft(args[2], "0") != "" {
		rounds, args = args[2], args[:1]
	}
	if len(args) != 1 || filepath.Base(args[0]) != args[0] || args[0] == "." || args[0] == ".." {
		return "", "", false
	}
	return args[0], rounds, true
}

// Working is whether a process of the run outlives its recorded loop, Python's _run_working: one
// carrying its marker, this process or an ancestor too, as when a worker calls `ak doctor`, or an
// `ak run resume` of it that has not recorded its pid yet, which a second resume would race.
func Working(dir string) bool {
	return slices.ContainsFunc(host.Carrying(dir), live) || resuming(dir)
}

// resuming is whether a live `ak run resume` of the run is at work: one writing the run's log, or
// this checkout's, its bin/ak or this program.  Another's that does not only follows the run from a
// terminal, and counted, it would keep the tick from resuming the loop it waits on.
func resuming(dir string) bool {
	self, _, _ := config.Running()
	return slices.ContainsFunc(Resumes(dir), func(resume Resume) bool {
		return resume.Writes || resume.Ak == self || resume.Ak == filepath.Join(config.Repo(), "bin", "ak")
	})
}

// A Resume is a live `ak run resume` of a run: the ak it runs, and whether it writes the run's log.
type Resume struct {
	Ak     string
	Writes bool
}

// Resumes are the live `ak run resume` processes of the run at dir, Python's watch.resumes: under
// any ak's bin/, a Python interpreter running it naming it next, as one enters its run's own
// version.  One started in the background writes the log; a terminal's starts the run there, then
// only follows it.
func Resumes(dir string) (found []Resume) {
	log, _ := os.Stat(filepath.Join(dir, "log.txt"))
	entries, _ := os.ReadDir("/proc")
	for _, entry := range entries {
		pid, err := strconv.Atoi(entry.Name())
		if err != nil || !live(pid) {
			continue
		}
		said, _ := os.ReadFile("/proc/" + entry.Name() + "/cmdline")
		args := strings.Split(strings.TrimSuffix(string(said), "\x00"), "\x00")
		if len(args) > 1 && strings.HasPrefix(filepath.Base(args[0]), "python") {
			args = args[1:]
		}
		if len(args) < 3 || args[1] != "run" || args[2] != "resume" || filepath.Base(args[0]) != "ak" || filepath.Base(filepath.Dir(args[0])) != "bin" {
			continue
		}
		if id, _, ok := ResumeArgs(args[3:]); !ok || id != filepath.Base(dir) {
			continue
		}
		out, err := os.Stat("/proc/" + entry.Name() + "/fd/1")
		found = append(found, Resume{Ak: args[0], Writes: err == nil && log != nil && os.SameFile(out, log)})
	}
	return found
}

// live is whether the process runs, not one that has exited and not yet been reaped.
func live(pid int) bool {
	stat, ok := host.ReadStat(pid)
	return ok && !stat.Exited()
}
