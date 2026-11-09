package seat

import "agentkit/internal/run"

// typeInto is watch.type_into, as a stop's reminder goes in: typeAtPrompt's line, its Enter sent
// whatever the composer shows of it by then.
func typeInto(name, line string, log func(string), stale func(string) bool) bool {
	return typeAtPane(name, "", line, nil, func(*run.Object) error { return nil }, log, stale, false)
}
