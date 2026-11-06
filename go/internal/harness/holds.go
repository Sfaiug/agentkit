package harness

// AsksHolds is whether Python asks that harness, now, what background work its seat still runs
// (its plugin `holds`), over what its last Stop listed, as Go does not yet.
func AsksHolds(name string) bool { return plugins[name].holds }
