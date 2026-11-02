package loop

import (
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
	"time"

	"agentkit/internal/box"
	"agentkit/internal/config"
	"agentkit/internal/handin"
	"agentkit/internal/host"
	"agentkit/internal/run"
	"agentkit/internal/worker"
)

// outCap is the most of a check's output a model is handed: the rest is in a file its line names.
const outCap = 20 * 1024

// flakyKey ignores varying values without depending on a suite's failure words, Python's
// gate.flaky_key: an absolute path can have another temporary root on each run, a test's name
// stays.
var flakyKey = regexp.MustCompile(`(?i)(^|[^\p{L}\p{N}_.])/[^\s'"` + "`" + `<>]+|\b(?:0x[0-9a-f]+|[0-9a-f]{8,}(?:-[0-9a-f]+)*)\b|\d+(?:\.\d+)?(?:e[+-]?\d+)?`)

// A ran is how one command ended: its status, and how a stop ended it, "" where none did.
type ran struct {
	code    int
	stopped string
	left    []string
}

// checks runs the commands while they produce output, with a ceiling on the whole list, Python's
// gate.run_done_when: each has its own silence window; one that exits non-zero runs once more at
// once, which decides, a pass that took the re-run said by a `flaky:` record; a stop ends the list.
// The log holds their output as they run and their records once they ended.
func (l *loop) checks(cmds []string, path string) (bool, string, error) {
	if err := os.MkdirAll(filepath.Dir(path), 0o777); err != nil {
		return false, "", err
	}
	progress, err := os.OpenFile(path, os.O_RDWR|os.O_CREATE|os.O_TRUNC|os.O_APPEND, 0o666)
	if err != nil {
		return false, "", err
	}
	defer progress.Close()
	deadline := time.Now().Add(l.ceiling)
	ok := true
	var chunks []string
	var spent, last, stopReason string
	var left []string
	unstarted := false
	for _, cmd := range cmds {
		var first *[2]int64
		var outcome ran
		var offset int64
		out := true
		for {
			if err := l.stopCheck(); err != nil {
				return false, "", err
			}
			remaining := time.Until(deadline)
			if remaining <= 0 {
				out = false
				break
			}
			fmt.Fprintf(progress, "$ %s\n", cmd)
			offset, _ = progress.Seek(0, io.SeekEnd)
			l.say("suite runs here: command is not sent to the suite helper (does not name AK_SHARD)")
			if outcome, err = l.boxed(cmd, remaining, progress, path); err != nil {
				return false, "", err
			}
			if outcome.code == 0 || first != nil || outcome.stopped != "" {
				break
			}
			end, _ := progress.Seek(0, io.SeekEnd)
			first = &[2]int64{offset, end}
		}
		if !out && first == nil {
			// out of time: starting this one would give it a limit of its own
			spent, unstarted = cmd, true
			chunks = append(chunks, "$ "+cmd+"\n[not run: the done-when limit was already spent]")
			break
		}
		ok = ok && outcome.code == 0 && outcome.stopped == ""
		said, err := cutFrom(progress, offset, l.dir, stem(path))
		if err != nil {
			return false, "", err
		}
		status := "exit " + strconv.Itoa(outcome.code)
		if outcome.stopped != "" {
			status = "killed at the limit"
		}
		chunks = append(chunks, strings.TrimRightFunc("$ "+cmd+"\n["+status+"]\n"+said, config.Space))
		if first != nil && outcome.code == 0 {
			record, err := l.flaky(cmd, progress, *first, offset, path)
			if err != nil {
				return false, "", err
			}
			chunks = append(chunks, record)
		}
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
	return ok, text, os.WriteFile(path, []byte(text), 0o666)
}

// boxed runs one command in the workspace in a box, its output into progress and activity being
// where that lands, until it ends, says nothing for the run's silence or spends limit.
func (l *loop) boxed(cmd string, limit time.Duration, progress *os.File, activity string) (ran, error) {
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
	var left []string
	ctx, watched := worker.Watch{Silence: l.silence, Ceiling: limit, Heard: worker.Written(activity), Marker: l.dir,
		Before: func() { left = stillRunning(l.dir) }}.Stop(l.ctx)
	code, err := box.RunCheck(ctx, []string{"bash", "-c", cmd}, env, l.workspace, out, progress)
	stopped := watched()
	if errors.Is(err, errors.ErrUnsupported) {
		return ran{}, notYet("the host has no box for a check", "a check here")
	}
	if err != nil {
		fmt.Fprintf(progress, "%s\n", err)
		return ran{code: 126}, nil
	}
	if l.ctx.Err() != nil {
		return ran{}, context.Cause(l.ctx)
	}
	return ran{code, stopped, left}, nil
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
	rows := []string{note, "failed output: " + config.Resolve(saved.Name())}
	kept := 0
	for _, line := range config.SplitLines(decoded(failed)) {
		if strings.TrimFunc(line, config.Space) != "" && !printed[flakyKey.ReplaceAllString(line, "${1}<varying>")] && kept < 20 {
			rows = append(rows, line)
			kept++
		}
	}
	return strings.Join(rows, "\n"), nil
}

// cutFrom is a binary file's bytes from start to its end as a model is handed them, Python's
// turns.cut_file: whole up to outCap, else its end under a line naming a file holding all of it,
// never read whole, as a check can print more than the run's memory holds.
func cutFrom(file *os.File, start int64, where, name string) (string, error) {
	size, err := file.Seek(0, io.SeekEnd)
	if err != nil {
		return "", err
	}
	line := ""
	if size-start > outCap {
		whole, err := os.CreateTemp(where, name+"-whole-*.log")
		if err != nil {
			return "", err
		}
		defer whole.Close()
		if _, err := io.Copy(whole, io.NewSectionReader(file, start, size-start)); err != nil {
			return "", err
		}
		line = "[only part of this output is shown; all of it is in " + config.Resolve(whole.Name()) + "]\n"
	}
	from := max(start, size-outCap)
	part := make([]byte, size-from)
	if _, err := file.ReadAt(part, from); err != nil && !errors.Is(err, io.EOF) {
		return "", err
	}
	return line + decoded(part), nil
}

// proof runs a finding's command on the workspace, Python's prompts.proof_on on a scratch run, its
// evidence as a record holds it: a check's walls, its output in a log of its own, cut as a hand-in's.
func (l *loop) proof(command, path string) (*run.Object, error) {
	if err := l.stopCheck(); err != nil {
		return nil, err
	}
	l.say("--- review proof: checking workspace")
	progress, err := os.OpenFile(path, os.O_RDWR|os.O_CREATE|os.O_TRUNC|os.O_APPEND, 0o666)
	if err != nil {
		return nil, err
	}
	defer progress.Close()
	fmt.Fprintf(progress, "$ %s (on workspace)\n", command)
	start, _ := progress.Seek(0, io.SeekEnd)
	outcome, err := l.boxed(command, l.ceiling, progress, path)
	if err != nil {
		return nil, err
	}
	progress.Seek(0, io.SeekEnd)
	output, err := handin.Excerpt(progress, start)
	if err != nil {
		return nil, err
	}
	status := "exit " + strconv.Itoa(outcome.code)
	if outcome.stopped != "" || outcome.code < 0 {
		status = "did not finish"
	}
	fmt.Fprintf(progress, "\n[%s]\n", status)
	return run.Fields("run", command, "commit", "workspace", "returncode", outcome.code, "output", output,
		"killed", outcome.stopped != ""), nil
}

// failing is the first check a done-when log says did not exit 0, for the reason a run ends with.
func failing(text string) string {
	for _, record := range strings.Split(text, "\n\n") {
		lines := strings.SplitN(record, "\n", 3)
		if len(lines) >= 2 && strings.HasPrefix(lines[0], "$ ") && lines[1] != "[exit 0]" {
			return "`" + strings.TrimPrefix(lines[0], "$ ") + "` " + lines[1]
		}
	}
	return "see donewhen.log"
}

// stem is a path's file name without its extension.
func stem(path string) string {
	name := filepath.Base(path)
	return strings.TrimSuffix(name, filepath.Ext(name))
}

// decoded is bytes as Python decodes them with errors="replace".
func decoded(data []byte) string {
	return strings.ToValidUTF8(string(data), "\uFFFD")
}
