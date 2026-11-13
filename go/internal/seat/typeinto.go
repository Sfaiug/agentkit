package seat

import "agentkit/internal/run"

// typeInto is watch.type_into, as a stop's reminder goes in: typeAtPrompt's text, only into a
// composer read empty and while stale says no, then its Enter, and one more where the line did
// not leave, whatever the composer and stale say by then, as an Enter withheld leaves a draft
// nobody can take back.  True once the line left the composer.
func typeInto(name, line string, log func(string), stale func(string) bool) bool {
	return typeAtPane(name, "", line, nil, func(*run.Object) error { return nil }, log, stale, false)
}
