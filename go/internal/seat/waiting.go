package seat

import "agentkit/internal/run"

// Waiting is whether the seat ended its turn on `ak wait` and what it named is not over yet
// (watch.waiting_on), as its ladder reads it.
func Waiting(name string) bool {
	file, _ := run.ReadJSON(seatFile(name))
	if file == nil {
		return false
	}
	going, _ := waitGoing(climbing{file: file})
	return going != nil
}
