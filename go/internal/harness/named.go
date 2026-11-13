package harness

// Named is a name that harness gave the conversation a seat's record is on (Current), asked so as
// to write nothing: "" only on proof it gave none yet, as a fresh OpenCode launch gives none before
// its first prompt, each file read on the way absent, or read whole and naming none.  Any other
// failure on the way is the error, as is a case Go leaves to Python.
func Named(name string, record map[string]any) (string, error) {
	if named := plugins[name].named; named != nil {
		return named(record)
	}
	return Current(name, record), nil
}
