package seat

// Typable is whether Go types into that seat: the harness its record names is one TypeAtPrompt
// types into, where a line for any other is Python's to type.
func Typable(name string) bool {
	own, _ := seatHarness(name)
	return typable(own)
}
