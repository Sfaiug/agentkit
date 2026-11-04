package task

import "strings"

// IsFix recognizes both current fix instructions and tasks saved before the tip check,
// as Python's Loop.fix_run does.
func IsFix(body string) bool {
	const checked = "Your checkout starts on the target branch's tip, fetched when this run " +
		"started. ak checked the command below there before your first turn. " +
		"Fix the root cause so it passes, and show it failing before the " +
		"fix and passing afterwards in your summary. If only the owner can decide, " +
		"run `ak hand-in blocked \"<question>\"`."
	return strings.Contains(body, checked) || strings.Contains(body, FixTheCommand)
}
