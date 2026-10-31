package update

import (
	"cmp"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"slices"
	"strings"
	"time"
	"unicode/utf8"

	"agentkit/internal/config"
	"agentkit/internal/lock"
)

const freshCap = 90 * time.Minute // Python's E2E_CAP: a fresh account, three harness installs and one real merged run

// gate runs acceptance gate key, "live" or "fresh", on the box as it stands, as Python's
// update.run_gate: whether it passed, the labels of the checks it failed, sorted, its own `FAIL`
// lines, and why.  A fresh-install gate that cannot run here is skipped, which passes; one that
// ran and failed no check clears its standing faults once they were told.
func (u *upgrade) gate(key string) (bool, []string, []string, string) {
	failed := u.log.Name() + ".failed"
	os.Remove(failed)
	mark, began := u.end(), now()
	env := []string{"AGENTKIT_ACCEPTANCE_REQUIRED=1", "AK_LIVE_FAILED=" + failed}
	passed, why := false, "failed"
	if key == "fresh" {
		passed, why = u.fresh(env)
	} else if passed = u.step([]string{"bash", filepath.Join(u.repo, "tests", "live.sh")}, env, liveCap*time.Second); passed {
		why = "passed"
	}
	if passed {
		notePass(key, began, now())
	}
	var labels []string
	if data, err := os.ReadFile(failed); err == nil && utf8.Valid(data) {
		for _, label := range config.SplitLines(string(data)) {
			if label != "" && !slices.Contains(labels, label) {
				labels = append(labels, label)
			}
		}
		slices.Sort(labels)
		os.Remove(failed)
	}
	if key == "fresh" {
		faults := filepath.Join(config.Home(), "state", "fresh-gate-faults", "handed")
		if passed && len(labels) == 0 && handed(faults)["told"] == true {
			os.Remove(faults)
		}
		passed = passed || strings.HasPrefix(why, "skipped:")
	}
	var lines []string
	for _, line := range config.SplitLines(u.since(mark)) {
		if strings.HasPrefix(line, "FAIL  ") {
			lines = append(lines, strings.TrimRightFunc(line, config.Space))
		}
	}
	return passed, labels, lines, why
}

// fresh runs the fresh-install gate where it can run, with env, as Python's update.fresh_gate;
// where it cannot, it is skipped.  The script exits 2 before its first check where the host
// cannot run it, with no acceptance line, and the line naming it says why.
func (u *upgrade) fresh(env []string) (bool, string) {
	if why := freshUnavailable(u.repo); why != "" {
		return false, "skipped: " + why
	}
	fmt.Fprintln(u.out, "update: running e2e-fresh.sh, the fresh-install gate")
	mark := u.end()
	if u.step([]string{"bash", filepath.Join(u.repo, "tests", "e2e-fresh.sh")}, env, freshCap) {
		return true, "passed (throwaway HOME with borrowed logins; clean host and interactive logins not exercised)"
	}
	said := u.since(mark)
	if strings.Contains(said, "acceptance:") || !strings.Contains(said, "[exit 2]") {
		return false, "failed"
	}
	reason := ""
	for _, line := range config.SplitLines(said) {
		if _, why, found := strings.Cut(line, "e2e-fresh.sh:"); found {
			reason = strings.TrimFunc(why, config.Space)
		}
	}
	return false, "skipped: " + cmp.Or(reason, "the fresh-install gate could not run on this host")
}

// freshUnavailable is why the fresh-install gate cannot even be attempted here, as Python's
// update.fresh_unavailable, or "".  Whether this host can run it is the gate's own to say.
func freshUnavailable(repo string) string {
	fresh := filepath.Join(repo, "tests", "e2e-fresh.sh")
	platform := runtime.GOOS
	if platform == "windows" {
		platform = "win32" // as Python's sys.platform calls it
	}
	switch {
	case !regular(fresh):
		return "no " + fresh
	case platform != "linux":
		return "Linux only (this is " + platform + ")"
	}
	return ""
}

// end is where the log ends now: the gates write to it straight.
func (u *upgrade) end() int64 {
	info, err := u.log.Stat()
	if err != nil {
		return 0
	}
	return info.Size()
}

// since is what was written to the log from mark on.
func (u *upgrade) since(mark int64) string {
	data, _ := io.ReadAll(io.NewSectionReader(u.log, mark, 1<<62))
	return decoded(data)
}

// notePass keeps a pass of check key, when it ended and how long it took, as Python's
// update._note_pass: the tick's margin for the logins a run of it borrows.  Under its lock,
// unless a later one is kept; a failed write costs a margin.
func notePass(key string, began, ended float64) {
	record := filepath.Join(config.Home(), "state", key+"-check-passed")
	held, err := lock.Wait(context.Background(), record+".lock")
	if err != nil {
		return
	}
	defer held.Close()
	var last []float64
	if data, err := os.ReadFile(record); err == nil && json.Unmarshal(data, &last) == nil && len(last) == 2 && last[0] >= ended {
		return
	}
	data, _ := json.Marshal([]float64{ended, ended - began})
	put(record, data)
}

// gateResult keeps each of plans' run of red gates for the tick to hand back, as Python's
// update.harness_gate_result: a pass clears it; its second red in a row, of gate or, with none,
// of its install, keeps one line naming titles.  A record that cannot be written costs its
// hand-back, never the upgrade.
func gateResult(plans []plan, passed bool, gate, logPath string, titles []string) {
	for _, each := range plans {
		check := filepath.Join(config.Home(), "state", "harness-gates", each.name)
		if passed {
			os.Remove(filepath.Join(check, "handed"))
			continue
		}
		record := handed(filepath.Join(check, "handed"))
		if record == nil {
			record = map[string]any{}
		}
		reds, _ := record["reds"].(float64)
		if reds >= 2 {
			continue
		}
		if record["reds"] = reds + 1; reds+1 == 2 {
			red, fix := "failed its gate twice in a row ("+gate+")", "harness upgrade gate"
			if gate == "" {
				red, fix = "could not be installed twice in a row", "harness install"
			}
			record["line"] = fitted("The "+each.name+" harness upgrade "+red, titles,
				"Log: "+tilde(logPath)+". Fix the "+fix+".")
			record["typed"], record["told"] = nil, false
		}
		data, _ := json.Marshal(record)
		if os.MkdirAll(check, 0o777) == nil {
			put(filepath.Join(check, "handed"), data)
		}
	}
}

// freshStanding hands back, once, the checks failed that the fresh-install gate failed on the
// release before too, naming their `FAIL` lines, as Python's update.fresh_standing: a line not
// yet told stands until the tick tells it; once told, no set of checks it told since the last
// clean pass hands back anything new.
func freshStanding(failed, lines []string, logPath string) {
	check := filepath.Join(config.Home(), "state", "fresh-gate-faults")
	record := handed(filepath.Join(check, "handed"))
	if record == nil {
		record = map[string]any{"told": true}
	}
	sets, _ := record["sets"].([]any)
	if record["told"] != true || slices.ContainsFunc(sets, func(set any) bool {
		said, _ := json.Marshal(set)
		listed, _ := json.Marshal(failed)
		return string(said) == string(listed)
	}) {
		return
	}
	data, _ := json.Marshal(map[string]any{"sets": append(sets, failed), "typed": nil, "told": false,
		"line": fitted("The fresh-install gate failed checks that fail on the release before too", lines,
			"Log: "+tilde(logPath)+". Fix the standing faults.")})
	if os.MkdirAll(check, 0o777) == nil {
		put(filepath.Join(check, "handed"), data)
	}
}

// handed is a hand-back record, nil where there is none to read.
func handed(path string) map[string]any {
	var record map[string]any
	if data, err := os.ReadFile(path); err != nil || json.Unmarshal(data, &record) != nil {
		return nil
	}
	return record
}

// fitted is head, the failed checks' titles and tail as one line a composer shows whole, as
// Python's update._fitted: each title whole or left out, and those left out counted.
func fitted(head string, titles []string, tail string) string {
	var line string
	for shown := len(titles); shown >= 0; shown-- {
		named := slices.Clone(titles[:shown])
		if left := len(titles) - shown; left > 0 {
			named = append(named, fmt.Sprintf("%d more failed checks left out", left))
		}
		line = head + ". " + tail
		if len(named) > 0 {
			line = head + ": " + strings.Join(named, " / ") + ". " + tail
		}
		if !config.TooLong(line) {
			break
		}
	}
	return line
}

// tilde is path as `~/...` under the home, as Python's config.tilde: a typed line naming it
// stays short however deep the home is.
func tilde(path string) string {
	if rest, err := filepath.Rel(config.UserHome(), path); err == nil && filepath.IsLocal(rest) {
		return "~/" + rest
	}
	return path
}
