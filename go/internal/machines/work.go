package machines

import (
	"errors"
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// Work is the work m's marks allow, as Python's machines.work: this one every kind, another as
// Takes takes config.MachineWork's; false where those cannot be read.
func (m Machine) Work() ([]string, bool) {
	if m.Name == Here {
		return []string{"turns", "tests"}, true
	}
	work, known := config.MachineWork(m.Name)
	return m.Takes(work), known
}

// MaxRuns is the most model turns m runs at once (`[machines."NAME"] max_runs`) as decimal digits,
// "" for no cap, as Python's machines.max_runs; false where config.toml cannot be read.
func (m Machine) MaxRuns() (string, bool) {
	if m.Name == Here {
		return "", true
	}
	return config.MachineMaxRuns(m.Name)
}

// Takes is the marks as m takes them: turns never where its probe last said macOS.
func (m Machine) Takes(work []string) []string {
	if m.said == nil || run.Text(m.said.Get("system")) != "macOS" {
		return work
	}
	return slices.DeleteFunc(slices.Clone(work), func(word string) bool { return word == "turns" })
}

// Save sets m's `work` marks, as config.SaveMachine writes them, with the marks implied.
func (m Machine) Save(work []string, keep func() error) error {
	implied, err := implied()
	if err != nil {
		return err
	}
	return config.SaveMachine(m.Name, work, implied, keep)
}

// implied is each other machine's marks as the old turns_on_machines switch implied them, which a
// save writes where the file still holds it.
func implied() ([]config.Marks, error) {
	var implied []config.Marks
	for _, each := range Known() {
		if each.Name == Here {
			continue
		}
		work, known := each.Work()
		if !known {
			return nil, errors.New("config.toml's marks cannot be read")
		}
		implied = append(implied, config.Marks{Machine: each.Name, Work: work})
	}
	return implied, nil
}
