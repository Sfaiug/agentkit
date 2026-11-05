package run

// MergedOver is whether a later run that merged replaced this one, of its title or relaunched from
// its branch: a relaunch still running settles nothing.
func (index Index) MergedOver(record *Object) bool {
	return index.replaced(record, "merged-from")
}
