package cli

import (
	"cmp"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"unicode/utf8"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/task"
	"agentkit/internal/worker"
)

func init() { commands["worker"] = oneTurn }

var workerValues = []string{"--workspace", "--out", "--session", "--role"}

func validateWorker(args []string) string {
	usage := commandhelp.Usage("worker")
	parsed, problem := parse(args, workerValues, nil, usage)
	if problem != "" {
		return problem
	}
	if len(parsed.words) != 2 {
		return usage
	}
	if role, ok := parsed.values["--role"]; ok && !contains(worker.Roles, role) {
		return fmt.Sprintf("--role must be one of %s (got %s)", strings.Join(worker.Roles, ", "), commandhelp.Quote(role))
	}
	task := config.Expand(parsed.words[1])
	if !isFile(task) {
		return "no such task file: " + task
	}
	workspace := config.Absolute(cmp.Or(parsed.values["--workspace"], "."))
	if !isDir(workspace) {
		return "no such workspace: " + workspace
	}
	if _, err := config.ModelNamed(parsed.words[0]); err != nil {
		return err.Error()
	}
	return ""
}

// oneTurn runs `ak worker` as Python's worker.main: one turn into --out, else
// ~/.agentkit/tmp/worker-<model>-<task's stem>, printing where its answer is and exiting as its
// adapter did.
func oneTurn(args []string, out, errOut io.Writer) int {
	parsed, _ := parse(args, workerValues, nil, "") // validateWorker refused what it cannot read
	model, path := parsed.words[0], config.Expand(parsed.words[1])
	into := parsed.values["--out"]
	if into == "" {
		stem := filepath.Base(path)
		if dot := strings.LastIndexByte(stem, '.'); dot > 0 && dot < len(stem)-1 {
			stem = stem[:dot]
		}
		into = filepath.Join(config.Home(), "tmp", "worker-"+model+"-"+stem)
	}
	into = config.Expand(into)
	body, err := os.ReadFile(path)
	if err != nil || !utf8.Valid(body) {
		return notImplemented(errOut, "worker") // what Python reads in its runtime's own words
	}
	workspace := config.Absolute(cmp.Or(parsed.values["--workspace"], "."))
	code, _, err := worker.Turn(model, cmp.Or(parsed.values["--role"], "executor"), task.Text(body), workspace, into, parsed.values["--session"])
	if errors.Is(err, worker.ErrPython) {
		return notImplemented(errOut, "worker")
	} else if err != nil {
		fmt.Fprintf(errOut, "ak worker: %s\n", err)
		return 2
	}
	fmt.Fprintln(out, filepath.Join(into, "final.md"))
	if code != 0 {
		fmt.Fprintf(errOut, "ak worker: %s exited %d; see %s\n", model, code, filepath.Join(into, "stderr.log"))
	}
	return code
}
