package seat

// Drafted is whether a line typed into that seat now would join text in its composer, where
// watch.composer_draft reads no "": no composer found whole on its screen, or a draft held in it.
// False for a harness Go does not type into, whose screen Go does not read.
func Drafted(name string) bool {
	own, _ := seatHarness(name)
	if !typable(own) {
		return false
	}
	held, drawn := (seatAt{name, own, "=" + name + ":"}).composer()
	return !drawn || held != ""
}
