//go:build linux

package gc

import (
	"math/big"
	"path/filepath"
	"slices"
	"strings"

	"golang.org/x/sys/unix"

	"agentkit/internal/config"
	"agentkit/internal/host"
	"agentkit/internal/run"
)

// What the automatic collection clears under a user manager, as Python's gc.forget_failed_units
// and gc.stop_test_units do, each through host.Systemctl.

const testUnitAge = day // no suite runs a day: a test-slice unit this old was left (gc.TEST_UNIT_AGE)

// clearUnits forgets ak's day-old failed units and stops test units a day old, where a user
// manager runs.
func clearUnits(report func(string)) {
	if host.UserManager() {
		forgetFailedUnits(report)
		stopTestUnits(report)
	}
}

// forgetFailedUnits resets each `agentkit-*` unit failed a day ago, only once no run that has not
// ended can need its OOM evidence: a run store that cannot be listed, or a record that cannot be
// read, keeps them all.
func forgetFailedUnits(report func(string)) {
	runs, err := reading(run.Runs(), true)
	if err != nil {
		return
	}
	names, err := runs.Readdirnames(-1)
	runs.Close()
	if err != nil {
		return
	}
	r, held := &reads{}, []string(nil)
	for _, name := range names {
		path := filepath.Join(run.Runs(), name, "run.json")
		record := r.json(path)
		if record == nil && present(path) {
			return
		}
		if record != nil && !run.Ended(record) {
			held = append(held, scopeUnits(record.Str("scope"))...)
		}
	}
	code, listed, err := host.Systemctl("list-units", "--failed", "--no-legend", "--plain", "--no-pager", "agentkit-*")
	if err != nil || code != 0 {
		return
	}
	for _, line := range config.SplitLines(listed) {
		unit := word(line)
		if !strings.HasPrefix(unit, "agentkit-") || slices.Contains(held, unit) {
			continue
		}
		code, shown, err := host.Systemctl("show", unit, "-p", "ActiveState", "-p", "StateChangeTimestampMonotonic")
		if err != nil || code != 0 {
			continue
		}
		fields := properties(shown)
		changed, ok := seconds(fields, "StateChangeTimestampMonotonic")
		if !ok || fields["ActiveState"] != "failed" || !expired(changed, monotonic(), day) {
			continue
		}
		if code, _, err := host.Systemctl("reset-failed", unit); err == nil && code == 0 {
			report("gc: reset-failed " + unit)
		}
	}
}

// stopTestUnits stops each unit in an `agentkit-test…` slice active for a day: it outlived the
// suite that started it, however that suite ended. Each unit's own age decides, never the
// slice's, as two suites share slice names; and no slice is stopped, which would take a
// neighbour's fresh units with it.
func stopTestUnits(report func(string)) {
	code, listed, err := host.Systemctl("list-units", "--no-legend", "--plain", "--no-pager", "--type=service,scope", "--state=active")
	if err != nil {
		return
	}
	var units []string
	for _, line := range config.SplitLines(listed) {
		if unit := word(line); unit != "" {
			units = append(units, unit)
		}
	}
	if code != 0 || units == nil {
		return
	}
	code, shown, err := host.Systemctl(append([]string{"show", "-p", "Id", "-p", "Slice", "-p", "ActiveEnterTimestampMonotonic"}, units...)...)
	if err != nil || code != 0 {
		return
	}
	for _, block := range strings.Split(shown, "\n\n") {
		fields := properties(block)
		entered, ok := seconds(fields, "ActiveEnterTimestampMonotonic")
		id, named := fields["Id"]
		if !ok || !strings.HasPrefix(fields["Slice"], "agentkit-test") || !expired(entered, monotonic(), testUnitAge) || !named {
			continue
		}
		// --no-block: a unit ignoring SIGTERM holds a blocking stop past the timeout
		if code, _, err := host.Systemctl("stop", "--no-block", id); err == nil && code == 0 {
			report("gc: stopped " + id + ", a test suite's unit a day old")
		}
	}
}

// scopeUnits is the unit names a record's scope might be, scope first (turns._scope_units).
func scopeUnits(scope string) []string {
	switch {
	case scope == "":
		return nil
	case strings.HasSuffix(scope, ".scope") || strings.HasSuffix(scope, ".service"):
		return []string{scope}
	}
	return []string{scope + ".scope", scope + ".service"}
}

// word is a line's first word, as Python's split() reads words; empty for a blank line.
func word(line string) string {
	if words := strings.FieldsFunc(line, config.Space); len(words) > 0 {
		return words[0]
	}
	return ""
}

// properties is `systemctl show`'s KEY=VALUE lines, a later one of a key winning.
func properties(text string) map[string]string {
	fields := map[string]string{}
	for _, line := range config.SplitLines(text) {
		if key, value, ok := strings.Cut(line, "="); ok {
			fields[key] = value
		}
	}
	return fields
}

// seconds is a monotonic timestamp's microseconds as seconds, 0 where systemd gave none; false
// where it is no number Python's int() reads.
func seconds(fields map[string]string, key string) (float64, bool) {
	text, given := fields[key]
	if !given {
		return 0, true
	}
	micros := config.Int(strings.TrimFunc(text, config.Space))
	if micros == nil {
		return 0, false
	}
	value, _ := new(big.Float).SetInt(micros).Float64()
	return value / 1e6, true
}

// monotonic is CLOCK_MONOTONIC in seconds, Python's time.monotonic(): systemd counts its
// *TimestampMonotonic from the same boot, so no date parsing or wall-clock change makes a recent
// change look old. Tests replace it.
var monotonic = func() float64 {
	var now unix.Timespec
	unix.ClockGettime(unix.CLOCK_MONOTONIC, &now)
	return float64(now.Sec) + float64(now.Nsec)/1e9
}
