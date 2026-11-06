package run

// Unfinished is a run that still owns its seat or awaits the owner's decision on its recovery,
// unless a later merged run replaced it (transitions.unfinished).
func (index Index) Unfinished(record *Object) bool {
	return Active(record) || NeedsRecovery(record) && !record.Truthy("recovery_acknowledged_at") && !index.MergedOver(record)
}
