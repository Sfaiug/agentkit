package harness

// AsksSwitchable is whether Python asks that harness's plugin whether its running seat takes a
// model at an effort from its `[switch]` lines (its plugin `switchable`), as Go does not yet.
func AsksSwitchable(name string) bool { return plugins[name].switchable }
