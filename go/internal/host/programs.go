package host

import (
	"bytes"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"slices"
	"strconv"
	"strings"
)

// A Process is one row of the process table: its parent and the words of its command.
type Process struct {
	Parent int
	Words  []string
}

// Processes is the process table from one `ps`, or nil where there is none.
func Processes() map[int]Process {
	out, err := exec.Command("ps", "-A", "-ww", "-o", "pid=", "-o", "ppid=", "-o", "args=").Output()
	if err != nil {
		return nil
	}
	table := map[int]Process{}
	for _, line := range strings.Split(string(out), "\n") {
		words := strings.Fields(line)
		if len(words) < 2 {
			continue
		}
		pid, err := strconv.Atoi(words[0])
		parent, failed := strconv.Atoi(words[1])
		if err == nil && failed == nil {
			table[pid] = Process{parent, words[2:]}
		}
	}
	return table
}

// Worker is whether the process runs for an ak worker: what runs under one belongs to a run.
// An environment it cannot read is no proof that it does.
func Worker(pid int) bool {
	environ, err := os.ReadFile("/proc/" + strconv.Itoa(pid) + "/environ")
	return err == nil && bytes.Contains(append([]byte{0}, environ...), []byte("\x00AK_RUN_ROLE=worker\x00"))
}

// The programs that run a script they are handed, which may be a harness (`node .../bin/codex`),
// each by its own option grammar: what starts an option, the short letters and long options
// that take the next word as their argument, and those after which there is no script file at
// all -- a command string, stdin, a module -- so no word that follows names what runs.
var interpreters = []struct {
	name                 *regexp.Regexp
	starts, takes, modes string
	longTakes, longModes []string
}{
	{regexp.MustCompile(`^(?:ba|da|z|k|mk)?sh$`), "-+", "oO", "cs", []string{"--rcfile", "--init-file"}, nil},
	{regexp.MustCompile(`^python[0-9.]*$`), "-", "WX", "cm", []string{"--check-hash-based-pycs"}, nil},
	{regexp.MustCompile(`^node(?:js)?$`), "-", "rC", "ep", []string{"--require", "--import", "--loader",
		"--experimental-loader", "--conditions", "--input-type", "--title", "--inspect-port", "--env-file"},
		[]string{"--eval", "--print"}},
}

// Program is what a process runs: its own program, or the script file an interpreter was
// handed, read past its options by its own grammar.  `bash -c 'claude || sleep 600'` was handed
// no file, and is bash.
func Program(words []string) string {
	if len(words) == 0 {
		return ""
	}
	name := filepath.Base(words[0])
	for _, grammar := range interpreters {
		if !grammar.name.MatchString(name) {
			continue
		}
		for i := 1; i < len(words); i++ {
			word := words[i]
			switch {
			case word == "--":
				if i+1 < len(words) && words[i+1] != "" {
					return filepath.Base(words[i+1])
				}
				return name
			case strings.HasPrefix(word, "--"):
				option, _, valued := strings.Cut(word, "=")
				if slices.Contains(grammar.longModes, option) {
					return name
				}
				if slices.Contains(grammar.longTakes, option) && !valued {
					i++
				}
			case word == "-":
				return name // the script is stdin
			case word == "":
			case strings.ContainsRune(grammar.starts, rune(word[0])):
				for place, letter := range word[1:] {
					if strings.ContainsRune(grammar.modes, letter) {
						return name
					}
					if strings.ContainsRune(grammar.takes, letter) {
						if place == len(word)-2 {
							i++ // its argument is the next word, not the script
						}
						break // ... or the rest of this one
					}
				}
			default:
				return filepath.Base(word)
			}
		}
		return name
	}
	return name
}
