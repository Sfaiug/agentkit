package cli

import (
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/machines"
	"agentkit/internal/seat"
)

// saveCap is the cloud's Monthly cap field (menu.config_machines' cap_field): what was typed,
// spaces around it aside, saved at once as `[google_cloud]`'s max_month where it is whole euros,
// 0 or more, in no more digits than Python's int() reads, so Python reads the file back; anything
// else is said, nothing written.
func saveCap(typed string) string {
	euros := strings.TrimFunc(typed, config.Space)
	cap := config.Int(euros)
	if cap == nil || strings.Trim(euros, "0123456789") != "" {
		return "the monthly cap must be a whole number of euros, 0 or more"
	}
	return saved(machines.Cloud.Save("max_month", cap, seat.KeepConfigEfforts))
}
