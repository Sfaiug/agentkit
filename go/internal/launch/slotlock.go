package launch

import "agentkit/internal/loop"

func init() {
	loop.HoldSlots = holdAdmission
	loop.WaitSlot = waitSlot
}
