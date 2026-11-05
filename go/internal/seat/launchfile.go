package seat

import (
	"crypto/rand"
	"encoding/hex"
	"os"
	"path/filepath"
	"slices"

	"agentkit/internal/commandhelp"
)

const launchBytes = 4

// launchFile is the file a seat's pane runs its harness by, which removes itself, and the pane's
// command that runs it.
func launchFile(state, name string, values []field, cmd []string) (string, string, error) {
	token := make([]byte, launchBytes)
	rand.Read(token)
	launch := filepath.Join(state, "launch-"+name+"."+hex.EncodeToString(token))
	// a pane's -e can set a variable, but not remove one the server holds
	script := "rm -f -- \"$0\"\n"
	if unset := slices.DeleteFunc(slices.Clone(values), func(f field) bool { return f.value != nil }); len(unset) > 0 {
		script += "unset"
		for _, f := range unset {
			script += " " + f.key
		}
		script += "\n"
	}
	err := os.WriteFile(launch, []byte(script+"exec "+commandhelp.ShellJoin(cmd)+"\n"), 0o666)
	return commandhelp.ShellJoin([]string{"sh", launch}), launch, err
}

// A launch can still be waiting for its pane to run it when another reader lists the seat.
// Its script changes no word and stays for that pane to consume.
func launchKind(kind, suffix string) bool {
	if kind != "launch" || len(suffix) != hex.EncodedLen(launchBytes) {
		return false
	}
	_, err := hex.DecodeString(suffix)
	return err == nil
}
