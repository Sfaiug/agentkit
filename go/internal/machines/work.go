package machines

import (
	"errors"
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/googlecloud"
	"agentkit/internal/run"
)

// Cloud is every machine ak rents, one not rented yet included: the one whose marks are
// `[google_cloud]`'s.
var Cloud = Machine{}

// Rented is whether m is the Cloud or a machine ak keeps a route to, whose marks are the cloud's.
func (m Machine) Rented() bool { return m.Name == "" || len(googlecloud.SSHConfig(m.Name)) > 0 }

// Work is the work m's marks allow, as Python's machines.work: this one every kind, another as
// Takes takes config.MachineWork's; false where those cannot be read.
func (m Machine) Work() ([]string, bool) {
	if m.Name == Here {
		return []string{"turns", "tests"}, true
	}
	work, known := config.MachineWork(m.marks())
	return m.Takes(work), known
}

// Takes is the marks as m takes them: turns never where its probe last said macOS, though the
// machines ak rents take theirs whatever a probe said.
func (m Machine) Takes(work []string) []string {
	if m.Rented() || m.said == nil || run.Text(m.said.Get("system")) != "macOS" {
		return work
	}
	return slices.DeleteFunc(slices.Clone(work), func(word string) bool { return word == "turns" })
}

// Save sets `key` of m's marks' table to `value`, its `work` or the cloud's `active`, as
// config.SaveMachine writes it, each other machine's marks written as the old turns_on_machines
// switch implied them where the file still holds it.
func (m Machine) Save(key string, value any, keep func() error) error {
	var implied []config.Marks
	for _, each := range append(Known(), Cloud) {
		if each.Name == Here || each.Name != "" && each.Rented() {
			continue
		}
		work, known := each.Work()
		if !known {
			return errors.New("config.toml's marks cannot be read")
		}
		implied = append(implied, config.Marks{Machine: each.Name, Work: work})
	}
	return config.SaveMachine(m.marks(), key, value, implied, keep)
}

// marks is the name of the table of m's marks, "" for the cloud's.
func (m Machine) marks() string {
	if m.Rented() {
		return ""
	}
	return m.Name
}
