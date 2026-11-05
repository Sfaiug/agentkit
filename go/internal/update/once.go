package update

import (
	"bytes"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"

	"agentkit/internal/config"
)

// updateOnce is Python's update_once: the command and tick each say a failure once per origin
// commit. With fetch off, target is already fetched, or empty for an install owed offline.
func updateOnce(env []string, checkout, where string, out io.Writer, target string, fetch bool) int {
	var said bytes.Buffer
	code := moveAgentkit(env, checkout, &said, target, fetch)
	if code != 0 {
		// a refusal comes before any pull, so origin is asked afresh: a stale origin/main would
		// hold a new commit to the one already said
		git(env, checkout, "fetch", "--quiet", "origin", "main")
		head, _ := git(env, checkout, "rev-parse", "origin/main")
		record := filepath.Join(config.Home(), "state", "agentkit-said-"+where)
		if last, err := os.ReadFile(record); err == nil && strings.TrimFunc(string(last), config.Space) == head {
			return code
		}
		os.WriteFile(record, []byte(head+"\n"), 0o666)
	}
	for _, line := range config.SplitLines(said.String()) {
		fmt.Fprintln(out, line)
	}
	return code
}
