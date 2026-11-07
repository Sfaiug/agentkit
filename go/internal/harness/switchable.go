package harness

// Switchable is whether that harness's running seat takes `model` at `effort` from its `[switch]`
// lines rather than only from a launch, as Python's plugin `switchable` says: by default it does.
func Switchable(name, model, effort string) bool {
	if hook := plugins[name].switchable; hook != nil {
		return hook(model, effort)
	}
	return true
}
