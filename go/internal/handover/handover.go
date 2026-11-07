// Package handover is the one way Go hands a case to Python ak, and no other exit 3 passes
// through it: the shadow cannot tell a hand-over by its exit, so where AK_HANDOVER names a file,
// each one leaves a line there first.  The line is the shadow's: nothing in Go reads it.
package handover

import (
	"fmt"
	"os"
	"path"
	"runtime"
	"strings"
)

// command is the words of the command this process carries out, as its dispatch read them.
var command string

// Runs is where dispatch names the command it carries out, by its words (`orch check`), for
// what it hands over; dispatch that reads another word names the command again.
func Runs(words string) { command = words }

// Exit is 3, for a case of the command running handed over at site, after "<command>: <site>"
// goes on the end of the file AK_HANDOVER names, where it names one.
func Exit(site string) int {
	if name := os.Getenv("AK_HANDOVER"); name != "" {
		if record, err := os.OpenFile(name, os.O_WRONLY|os.O_APPEND|os.O_CREATE, 0o600); err == nil {
			fmt.Fprintf(record, "%s: %s\n", command, site)
			record.Close()
		}
	}
	return 3
}

// Here is the Go file, under the module's root, and line of the call skip frames above Here's.
func Here(skip int) string {
	_, own, _, _ := runtime.Caller(0)
	_, file, line, _ := runtime.Caller(skip + 1)
	// this file is internal/handover under the root, a folder or, built with -trimpath, the module
	root := path.Dir(path.Dir(path.Dir(own)))
	return fmt.Sprintf("%s:%d", strings.TrimPrefix(file, root+"/"), line)
}
