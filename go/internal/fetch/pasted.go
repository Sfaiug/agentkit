package fetch

import (
	"fmt"
	"regexp"
	"slices"
	"strings"
	"time"

	"agentkit/internal/commandhelp"
)

// macPath is where a word the owner pasted from a Mac starts: a quote, or none, then a folder
// of a Mac user's or of its temporary files.
var macPath = regexp.MustCompile(`['"]?/(?:Users|var/folders)/`)

// Pasted is where each Mac file pasted into the owner's words can be read here, else the `ak
// fetch` that may fetch it later, all sharing one ten-second wait on the Mac
// (macbridge.pasted_context); "" where they paste none.  Each path is the shell word it starts,
// so quotes are read from the path, never from an apostrophe elsewhere in the sentence.
func Pasted(said string) string {
	var paths []string
	end := 0
	for _, at := range macPath.FindAllStringIndex(said, -1) {
		if at[0] < end {
			continue
		}
		path, took, ok := commandhelp.ShellWord(said[at[0]:])
		if !ok {
			break // an unclosed word took the rest of the words
		}
		end = at[0] + took
		if !slices.Contains(paths, path) {
			paths = append(paths, path)
		}
	}
	deadline := time.Now().Add(10 * time.Second)
	lines := make([]string, len(paths))
	for i, path := range paths {
		local, err := here(path, max(0, time.Until(deadline).Seconds()))
		if err != nil {
			lines[i] = fmt.Sprintf("%s: the Mac did not answer with a file (%v); try %s later.", path, err, retry(path))
			continue
		}
		lines[i] = path + " is at " + local
	}
	return strings.Join(lines, "\n")
}

// retry is the `ak fetch` that fetches path later.  The invoking shell unquotes its word, and
// normalize then reads what is left as a pasted word: quoted, and its backslashes escaped.
func retry(path string) string {
	quoted := func(word string) string { return commandhelp.ShellJoin([]string{word}) }
	return "ak fetch " + quoted(quoted(strings.ReplaceAll(path, `\`, `\\`)))
}
