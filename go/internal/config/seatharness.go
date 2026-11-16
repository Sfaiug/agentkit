package config

// SeatHarness is the harness a seat's record orchestrates on, as Python's watch.seat_model
// reads it, "" where no record names one.
func SeatHarness(name string) string { return SeatModel(name).Harness }

// SeatModel is the model a seat's record orchestrates on, Python's watch.seat_model: none where no
// record names one.
func SeatModel(name string) Model {
	_, record, err := ResolveSession(name)
	orchestrator, _ := record["orchestrator"].(string)
	model, unknown := ModelNamed(orchestrator)
	if err != nil || unknown != nil {
		return Model{}
	}
	return model
}
