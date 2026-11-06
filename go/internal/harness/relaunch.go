package harness

import "agentkit/internal/run"

// Relaunches includes harnesses whose resumed launch Go carries, even where a fresh launch
// needs evidence only Python learns.
func Relaunches(name string) bool {
	_, opens := Opens(name)
	return opens || plugins[name].launch != nil
}

// LaunchExtras is what a harness records and tells its process beyond the conversation id.
// The reopen path writes it under the same lock as that id and restores it on a failed start.
func LaunchExtras(name string) (*run.Object, []string) {
	if hook := plugins[name].launch; hook != nil {
		return hook()
	}
	return run.NewObject(), nil
}
