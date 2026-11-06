package harness

import "agentkit/internal/run"

// Relaunches includes harnesses whose resumed launch Go carries, even where a fresh launch
// needs evidence only Python learns: one whose launch writes a receipt Go reads its conversation
// back from among them.
func Relaunches(name string) bool {
	_, opens := Opens(name)
	own := plugins[name]
	return opens || own.launch != nil || own.launched != nil && own.owned != nil
}

// LaunchExtras is what a harness records and tells its process beyond the conversation id.
// The reopen path writes it under the same lock as that id and restores it on a failed start.
func LaunchExtras(name string) (*run.Object, []string) {
	if hook := plugins[name].launch; hook != nil {
		return hook()
	}
	return run.NewObject(), nil
}
