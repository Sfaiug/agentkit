package config

// SeatHarness is the harness a seat's record orchestrates on, as Python's watch.seat_model
// reads it, "" where no record names one.
func SeatHarness(name string) string {
	_, record, err := ResolveSession(name)
	orchestrator, _ := record["orchestrator"].(string)
	model, unknown := ModelNamed(orchestrator)
	if err != nil || unknown != nil {
		return ""
	}
	return model.Harness
}
