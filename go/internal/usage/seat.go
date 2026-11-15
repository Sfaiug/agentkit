package usage

// SeatSpent is the c screen's spent_meter: a meter gating the model reads 100% used, unless
// credits let the seat go on.
func (r *Readings) SeatSpent(name string) bool {
	if r.OnCredits(name) {
		return false
	}
	meters, _ := r.gating(name)
	for _, meter := range meters {
		if used(meter) >= 100 {
			return true
		}
	}
	return false
}
