package helper

import (
	"slices"
	"time"

	"agentkit/internal/googlecloud"
)

// lasts is whether Google ends alias more from now or later, ends the rentals that serve: any other
// machine lasts.
func lasts(ends []googlecloud.Rental, alias string, more time.Duration) bool {
	at := slices.IndexFunc(ends, func(rental googlecloud.Rental) bool { return rental.Name == alias })
	return at < 0 || time.Until(time.Unix(ends[at].Until, 0)) >= more
}

// soon is whether Google ends each of aliases with room before a machine asked for now serves: the
// next is then ready as the chosen one stops taking work, not run here meanwhile.
func soon(aliases []string, fits []fit, ends []googlecloud.Rental) bool {
	for i, alias := range aliases {
		if fits[i].count > 0 && lasts(ends, alias, googlecloud.Lead) {
			return false
		}
	}
	return true
}

// need asks the tick for a machine for pieces of that cost, the MiB read now: a VM's that ran out
// of memory may raise them meanwhile.
func need(cpus, memoryMB float64, repo, work string) {
	googlecloud.Need(cpuMB(cpus, memoryMB, least(repo)), work)
}

// cpuMB is the MiB each vCPU of a machine to rent must hold, rounded up: a vCPU's share of a
// piece's VM, beside the tenth of its memory the machine keeps (linux.sh's `left`).
func cpuMB(cpus, memoryMB float64, least int) int {
	mb, each := 10*eachMB(memoryMB, least), 9*int(max(cpus, vmCPUs))
	if mb%each > 0 {
		return mb/each + 1
	}
	return mb / each
}

// eachMB is the MiB a piece's VM gets: twice the piece's, as it holds its own kernel, page cache
// and clone too, or least where that is more.
func eachMB(memoryMB float64, least int) int {
	return int(max(2*memoryMB, float64(least)))
}
