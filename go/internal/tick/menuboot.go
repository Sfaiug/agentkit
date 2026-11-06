package tick

// ResumeAfterBoot is what Python's menu does first, resume_after_boot, as far as Go has it, under
// watch.json's lock on the menu's way to the terminal: a home with nobody to resume records this
// boot.  One with somebody is left as it is, and the menu's read refuses it (seat.Home.Settled).
func ResumeAfterBoot() error {
	if !noBootResume() {
		return nil
	}
	return bootBaseline()
}
