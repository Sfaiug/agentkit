package usage

// SeatSpent is the c screen's spent_meter: every meter the model watches,
// including its provider's session, unless credits let the seat go on.
func (r *Readings) SeatSpent(name string) bool {
	if r.OnCredits(name) {
		return false
	}
	meters, provider := r.gating(name)
	for _, meter := range objects(provider.Get("meters")) {
		if session(meter) {
			meters = append(meters, meter)
		}
	}
	for _, meter := range meters {
		if used(meter) >= 100 {
			return true
		}
	}
	return false
}
