package seat

import "agentkit/internal/hookfact"

// holding is the type of each piece of background work the seat holds (watch.holding): what its
// harness's last Stop listed, else, for a harness whose Stop lists none, what its screen last
// showed running.  Its harness's ending ends that work with it.
func holding(name string) []string {
	if work := hookfact.Standing(name).Holds; len(work) > 0 {
		return work
	}
	var work []string
	for _, task := range revivalFile(name).List("holds") {
		if task, ok := task.(string); ok { // each writer puts a task's type down as a string
			work = append(work, task)
		}
	}
	return work
}
