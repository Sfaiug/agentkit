package doctor

import (
	"agentkit/internal/googlecloud"
	"agentkit/internal/host"
)

// rented is the line on the machines ak rents while it may not, as Python's google_cloud.said
// words it: the best to rent now, or why there is none.
func rented() string {
	offered, err := googlecloud.Offers()
	if err != nil {
		return err.Error()
	}
	if best := googlecloud.Best(host.MBPerCPU(), offered); len(best) > 0 {
		return "best now " + best[0].String()
	}
	return "nothing offered"
}
