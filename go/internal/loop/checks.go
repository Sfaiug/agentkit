package loop

import (
	"cmp"
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"sort"
	"strconv"
	"strings"
	"syscall"
	"time"
	"unicode/utf8"

	"agentkit/internal/box"
	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/history"
	"agentkit/internal/host"
	"agentkit/internal/run"
)

// The bound on what a model is handed of a check's output, every handing-on of it reading these:
// outCap of one command or piece, the rest in a file its line names, and piecesCap of a suite's
// pieces together, as their number follows the machine and on 3 Nov 128 of them at outCap made a
// log the harnesses refused as too long.
const (
	outCap    = 20 * 1024
	piecesCap = 256 * 1024
)

// namesShard is a check run as a share of its suite, and namesChanged one narrowed to the files a
// change touches: Python's runner sets each.
var (
	namesShard   = regexp.MustCompile(`\bAK_SHARD\b`)
	namesChanged = regexp.MustCompile(`\bAK_CHANGED\b`)
)

// flakyKey ignores varying values without depending on a suite's failure words, Python's
// gate.flaky_key: an absolute path can have another temporary root on each run, a test's name
// stays.
var flakyKey = regexp.MustCompile(`(?i)(^|[^\p{L}\p{N}_.])/[^\s'"` + "`" + `<>]+|\b(?:0x[0-9a-f]+|[0-9a-f]{8,}(?:-[0-9a-f]+)*)\b|\d+(?:\.\d+)?(?:e[+-]?\d+)?`)

// A ran is how one command ended: its status, how a stop ended it, "" where none did, and whether
// the kernel killed it for memory (starved.go).
type ran struct {
	code    int
	stopped string
	left    []string
	starved bool
	testReport
}

// checks runs the commands while they produce output, with a ceiling on the whole list, Python's
// gate.run_done_when: each has its own silence window; one that exits non-zero runs once more at
// once, which decides, a pass that took the re-run said by a `flaky:` record; a stop ends the list.
// The log holds their output as they run and their records once they ended.  In the workspace,
// each go leaves its row in history as the round's done-when.
func (l *loop) checks(cmds []string, path string) (bool, string, error) {
	ok, text, _, err := l.checksIn(l.workspace, cmds, path, l.rows("done-when", ""))
	return ok, text, err
}

// checksIn is that in cwd, with each command's exit as the runner saw it, nil for one killed at the
// limit or never run, and none for those after a kill: what decides a proof, never the text.  Each
// go of a command, or of a piece of a suite, leaves its row in history under rows (nil for none),
// and the tests a command named red or flaky once its re-run ended.
func (l *loop) checksIn(cwd string, cmds []string, path string, rows *history.Checked, selections ...*checkSelection) (bool, string, []*int, error) {
	selection := selectedCheck(selections)
	if err := os.MkdirAll(filepath.Dir(path), 0o777); err != nil {
		return false, "", nil, err
	}
	progress, err := os.OpenFile(path, os.O_RDWR|os.O_CREATE|os.O_TRUNC|os.O_APPEND, 0o666)
	if err != nil {
		return false, "", nil, err
	}
	defer progress.Close()
	deadline := time.Now().Add(l.ceiling)
	ok := true
	var chunks []string
	var spent, last, stopReason string
	var left []string
	var marks []*int
	unstarted := false
	asked := clock() // a later go is asked for as the one before it ends
	for _, cmd := range cmds {
		var first *[2]int64
		var outcome ran
		var offset int64
		var pieced *string // what a suite run in pieces hands on, its pieces' shares
		var flaky, named []string
		out := true
		for {
			if err := l.stopCheck(); err != nil {
				return false, "", nil, err
			}
			remaining := time.Until(deadline)
			if remaining <= 0 {
				out = false
				break
			}
			fmt.Fprintf(progress, "$ %s\n", cmd)
			offset, _ = progress.Seek(0, io.SeekEnd)
			if namesShard.MatchString(cmd) && !selection.pinned() {
				// its pieces each went once more alone where red: the command is not run again
				text := ""
				if outcome, text, err = l.pieces(cwd, cmd, deadline, progress, path, rows); err != nil {
					return false, "", nil, err
				}
				pieced, asked = &text, clock()
				break
			}
			l.say("suite runs here: command is not sent to the suite helper (does not name AK_SHARD)")
			shard, only := selection.request()
			row := history.Check(rows, cmd, asked, "", l.say)
			outcome, err = l.boxed(cwd, cmd, shard, remaining, progress, path, false, only)
			row.End(exitOf(outcome, err))
			asked = clock()
			if err != nil {
				return false, "", nil, err
			}
			flaky = append(flaky, outcome.flaky...)
			if outcome.code == 0 || first != nil || outcome.stopped != "" {
				break
			}
			end, _ := progress.Seek(0, io.SeekEnd)
			first, named = &[2]int64{offset, end}, outcome.failed
		}
		if pieced == nil {
			if first != nil && outcome.code == 0 {
				flaky = append(flaky, named...) // the tests its first run named failed passed on its re-run
			}
			outcome.flaky, outcome.reds = flaky, outcome.confirmed
			if !selection.pinned() && outcome.code > 0 {
				outcome.reds = outcome.failed
			}
		}
		if !out && first == nil {
			// out of time: starting this one would give it a limit of its own
			spent, unstarted = cmd, true
			marks = append(marks, nil)
			chunks = append(chunks, "$ "+cmd+"\n[not run: the done-when limit was already spent]")
			break
		}
		ok = ok && outcome.code == 0 && outcome.stopped == ""
		selection.observe(cmd, outcome)
		if outcome.stopped != "" {
			marks = append(marks, nil)
		} else {
			code := outcome.code
			marks = append(marks, &code)
		}
		var said string
		if pieced != nil {
			said = *pieced
		} else if said, err = cutFrom(progress, offset, l.dir, stem(path), outCap); err != nil {
			return false, "", nil, err
		}
		status := "exit " + strconv.Itoa(outcome.code)
		if outcome.stopped != "" {
			status = "killed at the limit"
		}
		chunks = append(chunks, strings.TrimRightFunc("$ "+cmd+"\n["+status+"]\n"+said, config.Space))
		if first != nil && outcome.code == 0 {
			record, err := l.flaky(cmd, progress, *first, offset, path)
			if err != nil {
				return false, "", nil, err
			}
			chunks = append(chunks, record)
		}
		history.TestReds(rows, outcome.reds, outcome.flaky, l.say)
		if outcome.stopped != "" {
			spent, stopReason, left = cmd, outcome.stopped, outcome.left
			lines := config.SplitLines(strings.TrimFunc(said, config.Space))
			last = "(no output)"
			if len(lines) > 0 {
				last = lines[len(lines)-1]
			}
			if runes := []rune(last); len(runes) > 160 {
				last = string(runes[:159]) + "…"
			}
			break
		}
	}
	if spent != "" {
		ok = false
		line := fmt.Sprintf("done-when: stopped after %gh ceiling: %s (the limit was spent before it could start)", l.ceiling.Hours(), spent)
		if !unstarted {
			cause := fmt.Sprintf("%g min of silence", l.silence.Minutes())
			if stopReason != "silence" {
				cause = fmt.Sprintf("%gh ceiling", l.ceiling.Hours())
			}
			line = fmt.Sprintf("done-when: stopped after %s: %s (last output: %s)", cause, spent, last)
			for _, command := range left {
				line += "; still running: " + command
			}
		}
		chunks = append(chunks, line+", and the commands after it, if any, were not run.")
		l.say(line)
	}
	text := strings.Join(chunks, "\n\n")
	return ok, text, marks, os.WriteFile(path, []byte(text), 0o666)
}

// boxed runs one command in cwd in a box, its output into progress and activity being where that
// lands, until it ends, says nothing for the run's silence or spends limit; with a shard, as that
// piece of its suite.  A proof keeps its bytecode apart: same-size revisions can share a
// timestamp, making ignored bytecode look valid.
func (l *loop) boxed(cwd, cmd, shard string, limit time.Duration, progress *os.File, activity string, proof bool, only ...[]string) (ran, error) {
	out, err := os.MkdirTemp(filepath.Dir(activity), "")
	if err != nil {
		return ran{}, err
	}
	defer os.RemoveAll(out)
	env, err := checkEnv()
	if err != nil {
		return ran{}, err
	}
	// where a check names the tests that failed, as any command that takes part is told
	env["AK_FAILED"] = filepath.Join(out, "AK_FAILED")
	if shard != "" {
		env["AK_SHARD"] = shard
	}
	if err := nameTests(env, out, only); err != nil {
		return ran{}, err
	}
	if proof {
		env["PYTHONPYCACHEPREFIX"] = filepath.Join(out, "pycache")
	}
	if l.marker != "" {
		env[host.Marker] = l.marker
	}
	var left []string
	watch := host.Watch{Silence: l.silence, Ceiling: limit, Heard: host.Written(activity), Before: func() { left = stillRunning(cmp.Or(l.marker, l.dir)) }}
	code, stopped, err := box.RunCheck(l.ctx, watch, []string{"bash", "-c", cmd}, env, cwd, out, progress)
	if errors.Is(err, errors.ErrUnsupported) {
		return ran{}, notYet("the host has no box for a check", "a check here")
	}
	if errors.Is(err, syscall.EAGAIN) {
		return ran{}, err // no room to start it says nothing of the work: the tick runs it again (noroom.go)
	}
	if err != nil {
		fmt.Fprintf(progress, "%s\n", err)
		return ran{code: 126}, nil
	}
	if l.ctx.Err() != nil {
		return ran{}, context.Cause(l.ctx)
	}
	return reportedTests(ran{code: code, stopped: stopped, left: left}, out, only, progress), nil
}

// checkEnv is a check's environment: seatless, as the workers are, at the run's next depth.
func checkEnv() (map[string]string, error) {
	pairs, err := config.SeatlessEnv()
	if err != nil {
		return nil, err
	}
	env := map[string]string{}
	for _, pair := range pairs {
		key, value, _ := strings.Cut(pair, "=")
		if !slices.Contains(host.SuiteOwn, key) {
			env[key] = value
		}
	}
	return env, nil
}

// stillRunning is the live leaves of what the marker names, by command line, for the sentence that
// says what hung: read before the stop, while they are still there.
func stillRunning(marker string) []string {
	marked := host.Marked(marker)
	parents := map[int]bool{}
	for _, pid := range marked {
		if stat, ok := host.ReadStat(pid); ok && !stat.Exited() {
			parents[stat.Parent] = true
		}
	}
	sort.Ints(marked)
	var found []string
	for _, pid := range marked {
		said, err := os.ReadFile("/proc/" + strconv.Itoa(pid) + "/cmdline")
		if stat, ok := host.ReadStat(pid); !ok || stat.Exited() || parents[pid] || err != nil || len(said) == 0 {
			continue
		}
		found = append(found, strings.TrimSpace(strings.ReplaceAll(string(said), "\x00", " ")))
	}
	return found
}

// flaky keeps a failure its re-run passed over: the whole of it in a file of its own, and the lines
// its re-run did not print in the record, at most 20, Python's gate.flaky_record.
func (l *loop) flaky(cmd string, progress *os.File, first [2]int64, rerun int64, path string) (string, error) {
	failed := make([]byte, first[1]-first[0])
	if _, err := progress.ReadAt(failed, first[0]); err != nil {
		return "", err
	}
	end, _ := progress.Seek(0, io.SeekEnd)
	again := make([]byte, end-rerun)
	if _, err := progress.ReadAt(again, rerun); err != nil {
		return "", err
	}
	return l.flakyRecord(cmd, failed, again, path, -1)
}

// flakyRecord is that record of one failed output and its passing re-run, Python's
// gate.flaky_record: the lines it keeps stop at most bytes, none where that is negative, and no
// line ends blank, as a record is what lies between two blank lines.
func (l *loop) flakyRecord(cmd string, failed, again []byte, path string, most int) (string, error) {
	saved, err := os.CreateTemp(l.dir, stem(path)+"-failed-*.log")
	if err != nil {
		return "", err
	}
	defer saved.Close()
	saved.Write(failed)
	printed := map[string]bool{}
	for _, line := range config.SplitLines(decoded(again)) {
		printed[flakyKey.ReplaceAllString(line, "${1}<varying>")] = true
	}
	note := "flaky: " + cmd + " failed, then passed on its re-run"
	l.say("done-when: " + note)
	var lines []string
	for _, line := range config.SplitLines(decoded(failed)) {
		if strings.TrimFunc(line, config.Space) != "" && !printed[flakyKey.ReplaceAllString(line, "${1}<varying>")] && len(lines) < 20 {
			lines = append(lines, line)
		}
	}
	diff := strings.Join(lines, "\n")
	if most >= 0 && len(diff) > most {
		diff = strings.ToValidUTF8(diff[:most], "")
	}
	rows := []string{note, "failed output: " + config.Resolve(saved.Name())}
	if diff = strings.TrimRightFunc(diff, config.Space); diff != "" {
		rows = append(rows, diff)
	}
	return strings.Join(rows, "\n"), nil
}

// cutFrom is a binary file's bytes from start to its end as a model is handed them, Python's
// turns.cut_file: whole up to most bytes, else its end under a line naming a file holding all of
// it, never read whole, as a check can print more than the run's memory holds.  Replacement
// characters can grow the end past most: it is cut there again, at a whole character.
func cutFrom(file *os.File, start int64, where, name string, most int64) (string, error) {
	size, err := file.Seek(0, io.SeekEnd)
	if err != nil {
		return "", err
	}
	from := max(start, size-most)
	part := make([]byte, size-from)
	if _, err := file.ReadAt(part, from); err != nil && !errors.Is(err, io.EOF) {
		return "", err
	}
	end := decoded(part)
	line := ""
	if size-start > most || int64(len(end)) > most {
		if line, err = kept(io.NewSectionReader(file, start, size-start), where, name); err != nil {
			return "", err
		}
	}
	return line + strings.ToValidUTF8(end[max(0, int64(len(end))-most):], ""), nil
}

// kept saves output whole in a new file under where, the line naming it heading any part of it a
// model is handed, so nothing a check printed is out of its reach, Python's turns.kept.
func kept(output io.Reader, where, name string) (string, error) {
	whole, err := os.CreateTemp(where, name+"-whole-*.log")
	if err != nil {
		return "", err
	}
	defer whole.Close()
	if _, err := io.Copy(whole, output); err != nil {
		return "", err
	}
	return "[only part of this output is shown; all of it is in " + config.Resolve(whole.Name()) + "]\n", nil
}

// proof runs a finding's command on the workspace, Python's prompts.proof_on on a scratch run, its
// evidence as a record holds it.
func (l *loop) proof(command, path string) (*run.Object, error) {
	asked := clock()
	if err := l.stopCheck(); err != nil {
		return nil, err
	}
	code, output, killed, err := l.proved(l.workspace, command, path, "", asked)
	if err != nil {
		return nil, err
	}
	return run.Fields("run", command, "commit", "workspace", "returncode", code, "output", output, "killed", killed), nil
}

// asStopped is err where it is a git that stopped, nil otherwise.
func asStopped(err error) error {
	var stopped *gitcall.Stopped
	if errors.As(err, &stopped) {
		return stopped
	}
	return nil
}

// stem is a path's file name without its extension.
func stem(path string) string {
	name := filepath.Base(path)
	return strings.TrimSuffix(name, filepath.Ext(name))
}

// decoded is bytes as Python decodes them with errors="replace": one replacement character for
// each lone bad byte or character cut short, where strings.ToValidUTF8 makes a run of them one.
func decoded(data []byte) string {
	var text strings.Builder
	text.Grow(len(data))
	for len(data) > 0 {
		r, size := utf8.DecodeRune(data)
		if r == utf8.RuneError && size == 1 {
			for size < len(data) && !utf8.FullRune(data[:size+1]) {
				size++
			}
		}
		text.WriteRune(r)
		data = data[size:]
	}
	return text.String()
}
