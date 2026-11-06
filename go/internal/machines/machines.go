// Package machines is what each machine ak may use is, as Python's agentkit/machines.py: each tick
// asks them all, and state/machines.json keeps their last three days' checks for `ak doctor` and
// `c`'s Machines page.
package machines

import (
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/googlecloud"
	"agentkit/internal/run"
)

const (
	Here = "this one" // the machine ak runs on, by the name its record keeps
	day  = 86400      // seconds
)

// A Machine is one ak may use as the ticks found it: its checks, oldest first, each [when,
// whether it answered], and what it said when it last answered, nil for never.
type Machine struct {
	Name   string
	until  int64 // the end of a rental that serves, 0 for any other
	checks []any
	said   *run.Object
}

// Known is every machine ak may use, this one first, off one reading of the ticks' record.
func Known() []Machine {
	names, record, rentals := known()
	machines := make([]Machine, len(names))
	for i, name := range names {
		entry := record.Dict(name)
		if entry == nil {
			entry = run.NewObject()
		}
		machines[i] = Machine{Name: name, checks: entry.List("checks"), said: entry.Dict("said")}
		if said := machines[i].said; said != nil && len(said.Keys()) == 0 {
			machines[i].said = nil
		}
		if at := slices.IndexFunc(rentals, func(r googlecloud.Rental) bool { return r.Name == name }); at >= 0 && name != Here {
			machines[i].until = rentals[at].Until
		}
	}
	return machines
}

// known is every machine ak may use, this one first: config.toml's, then those ak rents that
// serve; the ticks' record of them, empty where it cannot be read; and those rentals.
func known() ([]string, *run.Object, []googlecloud.Rental) {
	record := run.NewObject()
	if data, err := os.ReadFile(path()); err == nil {
		if value, err := run.Decode(data); err == nil {
			if read, ok := value.(*run.Object); ok {
				record = read
			}
		}
	}
	names, rentals := append([]string{Here}, config.MachineNames()...), googlecloud.Serving()
	for _, rental := range rentals {
		names = append(names, rental.Name)
	}
	var unique []string
	for _, name := range names {
		if name != "" && !slices.Contains(unique, name) {
			unique = append(unique, name)
		}
	}
	return unique, record, rentals
}

func path() string { return filepath.Join(config.Home(), "state", "machines.json") }

// String is `ak doctor`'s line of the machine, off its checks and what it said when it last
// answered.
func (m Machine) String() string {
	kind := kindOf(m.checks, m.said)
	if m.said == nil {
		return fmt.Sprintf("%s: %s · never answered", m.Name, kind)
	}
	said := m.said
	number := func(key string) float64 {
		value, _ := said.Num(key)
		return value
	}
	words := []string{kind, run.Text(said.Get("system")) + " " + run.Text(said.Get("processor")),
		fmt.Sprintf("%s cores, load %.1f", run.Text(said.Get("cores")), number("load")),
		fmt.Sprintf("%s, %s free", gb(number("memory_mb")), gb(number("free_mb"))),
		gb(number("disk_free_mb")) + " disk free"}
	if said.Truthy("battery") {
		power := "on battery"
		if said.Truthy("power") {
			power = "on power"
		}
		words = append(words, power)
	}
	words = append(words, "last answered "+when(number("at")))
	return m.Name + ": " + strings.Join(words, " · ")
}

// kindOf is `sometimes on`, at once for a battery, `new` or `always on`: one answer in twenty may
// go to a network blip, but a laptop shut every night misses about a third.
func kindOf(checks []any, said *run.Object) string {
	if said != nil && said.Truthy("battery") {
		return "sometimes on"
	}
	if len(checks) == 0 {
		return "new"
	}
	first, _ := run.Num(at(checks[0], 0))
	last, _ := run.Num(at(checks[len(checks)-1], 0))
	if last-first < day {
		return "new"
	}
	answered := 0
	for _, check := range checks {
		if yes, _ := at(check, 1).(bool); yes {
			answered++
		}
	}
	if 20*answered >= 19*len(checks) {
		return "always on"
	}
	return "sometimes on"
}

// at is that item of a check, [when, whether it answered].
func at(check any, item int) any {
	if pair, ok := check.([]any); ok && item < len(pair) {
		return pair[item]
	}
	return nil
}

func gb(mb float64) string {
	gb := mb / 1024
	if gb < 10 {
		return strings.TrimSuffix(fmt.Sprintf("%.1f", gb), ".0") + " GB"
	}
	return fmt.Sprintf("%.0f GB", gb)
}

// when is its hour and minute, with its day unless that is today.
func when(stamp float64) string {
	then, now := time.Unix(int64(stamp), 0), time.Now()
	if then.Format(time.DateOnly) == now.Format(time.DateOnly) {
		return then.Format("15:04")
	}
	return then.Format("2 Jan 15:04")
}
