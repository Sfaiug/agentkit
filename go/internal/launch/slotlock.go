package launch

import (
	"agentkit/internal/config"
	"agentkit/internal/loop"
)

func init() {
	loop.HoldSlots = holdAdmission
	loop.WaitSlot = waitSlot
	loop.Drivable = func(bound config.Binding, numbers config.Numbers) error { return drivable(nil, bound, numbers) }
}
