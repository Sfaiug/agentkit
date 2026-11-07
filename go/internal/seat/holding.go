package seat

import (
	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/hookfact"
	"agentkit/internal/run"
)

// holding is the type of each piece of background work the seat holds (watch.holding): what its
// harness's last Stop listed, else, for a harness whose Stop lists none, what its screen last
// showed running -- unless its harness, asked now, says what still runs, as work whose end starts
// no turn outlives the Stop that listed it.  A seat that held nothing is not asked.  Its harness's
// ending ends that work with it.
func holding(name string) []string {
	work := hookfact.Standing(name).Holds
	if len(work) == 0 {
		for _, task := range revivalFile(name).List("holds") {
			if task, ok := task.(string); ok { // each writer puts a task's type down as a string
				work = append(work, task)
			}
		}
	}
	record, _ := run.ReadJSON(ownFile("session", name))
	if len(work) == 0 || record == nil {
		return work
	}
	if now, asked := harness.Holds(config.SeatHarness(name), record); asked {
		return now
	}
	return work
}
