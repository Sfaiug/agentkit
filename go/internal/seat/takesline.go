package seat

// TakesLine is whether a line typed into that seat now would go in, by what TypeAtPrompt reads
// before it types: for a caller that must not act on what the line says unless the seat takes it.
func TakesLine(name string) bool {
	own, _ := seatHarness(name)
	if !typable(own) {
		return false
	}
	pane, _, _, found := linePane(name, "")
	at := seatAt{name, own, pane}
	return found && at.open() && at.settled()
}
