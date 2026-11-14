package seat

import "agentkit/internal/screen"

// PastText is whether a line for that seat would wait on text Python's editor may type it past
// (watch._past_text), which Go has no editor for: its composer drawn whole and holding text other
// than that line, or ak's editor keeping text of it.  False for a harness Go does not type into.
func PastText(name, line string) bool {
	own, _ := seatHarness(name)
	if !typable(own) {
		return false
	}
	pane, _, _, found := linePane(name, "")
	if !found {
		return false
	}
	at := seatAt{name, own, pane}
	held, drawn := at.composer()
	return drawn && held != "" && held != screen.Unspaced(keyed(line)) || at.editorKept()
}
