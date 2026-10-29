// Package agent says which of a tmux server's sessions run no agent. It hides one `ps` reading,
// each interpreter's option grammar, the adapters' program names, and the worker role: a harness
// an ak worker runs, and everything under it, belongs to a run, not to a seat.
package agent

import (
	"fmt"
	"os"
	"os/exec"
	"path"
	"regexp"
	"slices"
	"strconv"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/tmux"
)

// Agentless is whether no harness runs under a live pane of any of those sessions. It is not
// where tmux, `ps` or the manifests do not answer, or a pattern among them is one Go does not
// read; a pane the reading has not seen has ended, and runs nothing.
func Agentless(server string, names []string) bool {
	if len(names) == 0 {
		return true
	}
	pids, answered := tmux.Panes(server, names)
	patterns, err := config.Programs()
	harness, refused := globs(patterns)
	commands, children := processes()
	return answered && err == nil && refused == nil && commands != nil && !runsAgent(pids, commands, children, harness)
}

// runsAgent is whether a harness is at or under those processes, one no worker runs: a worker's
// harness is a run's, and nothing under it makes a seat.
func runsAgent(pids []int, commands map[int][]string, children map[int][]int, harness *regexp.Regexp) bool {
	stack, seen := slices.Clone(pids), map[int]bool{}
	for len(stack) > 0 {
		pid := stack[len(stack)-1]
		stack = stack[:len(stack)-1]
		words, ok := commands[pid]
		if !ok || seen[pid] {
			continue
		}
		seen[pid] = true
		if !harness.MatchString(program(words)) {
			stack = append(stack, children[pid]...)
		} else if !worker(pid) {
			return true
		}
	}
	return false
}

// globs is one expression matching what any of the patterns does as Python's fnmatchcase
// reads them: `*` is any run of characters, `?` any one, and every other character itself,
// `\` too. There a `[` opens a class, whose rules Go does not rebuild: it refuses the pattern.
func globs(patterns []string) (*regexp.Regexp, error) {
	var each []string
	for _, pattern := range patterns {
		if strings.Contains(pattern, "[") {
			return nil, fmt.Errorf("harness pattern %q: Go does not read a `[`", pattern)
		}
		// QuoteMeta writes each `*` and `?` as `\*` and `\?`, and any `*` or `?` it writes is one of those.
		each = append(each, strings.NewReplacer(`\*`, ".*", `\?`, ".").Replace(regexp.QuoteMeta(pattern)))
	}
	return regexp.Compile(`^(?s:` + strings.Join(each, "|") + `)$`)
}

var environ = func(pid int) ([]byte, error) { return os.ReadFile("/proc/" + strconv.Itoa(pid) + "/environ") }

// worker is whether the process's environment, where /proc shows it, says it is an ak worker.
// One Go cannot read is no proof that it is.
func worker(pid int) bool {
	env, err := environ(pid)
	return err == nil && slices.Contains(strings.Split(string(env), "\x00"), "AK_RUN_ROLE=worker")
}

// processes is each process's command and children by its ID, from one `ps`; nil without one.
func processes() (map[int][]string, map[int][]int) {
	out, err := exec.Command("ps", "-A", "-ww", "-o", "pid=", "-o", "ppid=", "-o", "args=").Output()
	if err != nil {
		return nil, nil
	}
	return parse(string(out))
}

// parse reads the lines of `ps`: a process ID, its parent's, then its command's words.
func parse(out string) (map[int][]string, map[int][]int) {
	commands, children := map[int][]string{}, map[int][]int{}
	for _, line := range strings.Split(out, "\n") {
		var pid, parent int
		if _, err := fmt.Sscan(line, &pid, &parent); err == nil {
			commands[pid], children[parent] = strings.Fields(line)[2:], append(children[parent], pid)
		}
	}
	return commands, children
}

// The programs that run a script they are handed, which may be a harness (`node .../bin/codex`),
// each by its own option grammar: what starts an option, the short letters and long options
// that take the next word as their argument, and those after which there is no script file at
// all -- a command string, stdin, a module -- so no word that follows names what runs.
var interpreters = []grammar{
	{regexp.MustCompile(`^(?:ba|da|z|k|mk)?sh$`), "-+", "oO", "cs", []string{"--rcfile", "--init-file"}, nil},
	{regexp.MustCompile(`^python[0-9.]*$`), "-", "WX", "cm", []string{"--check-hash-based-pycs"}, nil},
	{regexp.MustCompile(`^node(?:js)?$`), "-", "rC", "ep", []string{"--require", "--import", "--loader",
		"--experimental-loader", "--conditions", "--input-type", "--title", "--inspect-port", "--env-file"},
		[]string{"--eval", "--print"}},
}

type grammar struct {
	name                 *regexp.Regexp
	starts, takes, modes string
	longTakes, longModes []string
}

// program is what a process is running: its own program, or the script file an interpreter was
// handed. `bash -e /opt/bin/claude` runs claude; `bash -c 'claude || sleep 600'` outlives the
// claude it started, and is bash; `ssh claude sleep 600` runs ssh, whatever its host is called.
func program(words []string) string {
	if len(words) == 0 {
		return ""
	}
	name := path.Base(words[0])
	at := slices.IndexFunc(interpreters, func(g grammar) bool { return g.name.MatchString(name) })
	if at < 0 {
		return name
	}
	g := interpreters[at]
	for i := 1; i < len(words); i++ {
		word := words[i]
		switch {
		case word == "--" && i+1 < len(words):
			return path.Base(words[i+1])
		case word == "--", word == "-":
			return name // the script is stdin, or there is none
		case strings.HasPrefix(word, "--"):
			option, _, valued := strings.Cut(word, "=")
			if slices.Contains(g.longModes, option) {
				return name
			}
			if slices.Contains(g.longTakes, option) && !valued {
				i++
			}
		case strings.ContainsRune(g.starts, rune(word[0])):
			for place := 1; place < len(word); place++ {
				if strings.IndexByte(g.modes, word[place]) >= 0 {
					return name
				}
				if strings.IndexByte(g.takes, word[place]) >= 0 {
					if place == len(word)-1 {
						i++ // its argument is the next word, not the script
					}
					break // ... or the rest of this one
				}
			}
		default:
			return path.Base(word)
		}
	}
	return name
}
