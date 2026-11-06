package harness

import "agentkit/internal/run"

// CanLaunch includes harnesses whose launch writes its own evidence rather than
// a launcher-issued conversation. Reopen's existing admission stays its own.
func CanLaunch(name string) bool {
	_, known := Opens(name)
	return known || plugins[name].launched != nil
}

// Launched is the record and environment Python's plugin.launched hands a launch.
// The caller writes the fields under the record lock before starting the harness.
func Launched(name, cwd, conversation string, before *run.Object) (*run.Object, []string, error) {
	if hook := plugins[name].launched; hook != nil {
		return hook(cwd, conversation, before)
	}
	var owned, source any
	if conversation != "" {
		owned, source = conversation, "launcher"
	}
	issued := run.Fields("conversation", owned, "id_source", source, "resumable", conversation != "", "before", nil)
	extra, env := LaunchExtras(name)
	for _, key := range extra.Keys() {
		issued.Set(key, extra.Get(key))
	}
	return issued, env, nil
}

// Retire drops only the evidence that invocation owned, as plugin.retire does.
func Retire(name string, record *run.Object) error {
	if hook := plugins[name].retire; hook != nil && record != nil {
		return hook(record)
	}
	return nil
}
