package googlecloud

import (
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"strconv"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// ready is the seconds a machine takes to come up: no rent meanwhile, nor one for a shorter life.
const ready = 600

// noted is the most MiB a vCPU a suite noted for work marked since the last pass, 0 for none,
// taken: a suite noting next notes anew (google_cloud._noted).
func noted(work []string) int {
	need := needPath()
	if os.Rename(need, need+".taken") != nil {
		return 0
	}
	data, err := os.ReadFile(need + ".taken")
	if err != nil {
		return 0
	}
	most := 0
	for _, line := range config.SplitLines(string(data)) {
		words := append(strings.Fields(line), "tests") // a need of no kind is tests'
		if len(words) == 1 || !slices.Contains(work, words[1]) {
			continue
		}
		mib, err := strconv.Atoi(words[0])
		if err != nil {
			return 0
		}
		most = max(most, mib)
	}
	return most
}

// left is the euros the cap leaves to rent with: less the month's spend and what the machines on
// the meter hold to their ends, one asked for by name its whole life (google_cloud._rent).
func left(cap, spent float64, ledger *run.Object, now float64) float64 {
	held := 0.0
	for _, key := range ledger.Dict("machines").Keys() {
		one := ledger.Dict("machines").Dict(key)
		price, _ := one.Num("price")
		until, _ := one.Num("until")
		from := now
		if one.Has("from") {
			from, _ = one.Num("from")
		}
		held += price * max(0, until-from)
	}
	return cap - spent - held/3600
}

// comingUp is whether a machine comes up, no rent meanwhile: one on the meter by name, or listed
// without answering it is set up, asked for less than ready ago.
func comingUp(ledger *run.Object, listed []Machine, held map[string]int, now float64) bool {
	for _, key := range ledger.Dict("machines").Keys() {
		if from, _ := ledger.Dict("machines").Dict(key).Num("from"); now-from < ready {
			return true
		}
	}
	return slices.ContainsFunc(listed, func(one Machine) bool {
		seconds, answered := held[one.ID]
		return !(answered && seconds >= 0) && now-one.Created < ready
	})
}

// unrented is why no machine is rented for wanted MiB a vCPU where the cap leaves nothing, as
// Python's _rent says it, the last of the best offers it tried: each falls short of a machine's
// time to come up.
func unrented(wanted int, offered []Offer, cap, left float64) string {
	best := Best(wanted, offered)
	if len(best) == 0 {
		return fmt.Sprintf("nothing offered with %d MiB a vCPU", wanted)
	}
	return fmt.Sprintf("rents nothing: €%.2f of €%.2f spent this month or held to the machines' ends "+
		"leaves less than %d minutes of %s", cap-left, cap, ready/60, best[len(best)-1].Name)
}

func needPath() string { return filepath.Join(config.Home(), "state", "google-cloud-need") }
