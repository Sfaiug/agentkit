package googlecloud

import (
	"fmt"
	"os"
	"slices"
	"time"

	"agentkit/internal/config"
)

// Lead is how long a machine asked for now takes to serve: the tick's next pass rents it, and it
// comes up.
const Lead = (ready + pass) * time.Second

// Rents is whether ak may rent a machine for work, "tests" or "turns": `[google_cloud]` active, its
// marks taking that work.
func Rents(work string) bool {
	active, _ := config.CloudBudget()
	marks, _ := config.MachineWork("")
	return active && slices.Contains(marks, work)
}

// Need asks the tick's next pass for a machine of mbPerCPU MiB a vCPU for work no machine took in
// time, while ak rents for it (google_cloud.need); it fails nothing.
func Need(mbPerCPU int, work string) {
	if !Rents(work) {
		return
	}
	if noted, err := os.OpenFile(needPath(), os.O_WRONLY|os.O_APPEND|os.O_CREATE, 0o666); err == nil {
		fmt.Fprintf(noted, "%d %s\n", mbPerCPU, work)
		noted.Close()
	}
}
