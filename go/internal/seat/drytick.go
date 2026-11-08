package seat

// DryTick has every look until end share one dry look (dryLook), so a dry tick's later rows read
// what its earlier ones would have saved, as a real tick's read what they saved: its notification
// retry reads the word its seat health row would publish.
func DryTick() (end func()) {
	drying = dryLook{}
	return func() { drying = nil }
}

// Drying is whether the look under way is a dry one, for a row's reading of the seat it looks at.
func Drying() bool { return drying != nil }
