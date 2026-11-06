package tick

import (
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// ResumeAfterBoot is what Python's menu does first, resume_after_boot, as far as Go has it, under
// watch.json's lock on the menu's way to the terminal: a home with nobody to resume records this
// boot.  One with somebody is Python's, whose menu shows what it reopened.
func ResumeAfterBoot() error {
	return afterBoot(false, func(_ *run.Object, _ string, back []seat.Comeback) error {
		if len(back) > 0 {
			return errLeft
		}
		return nil
	})
}
