// Package contract is `ak contract [HARNESS] [--snapshot FILE] [--counts FILE]`, Python's
// agentkit/contract.py: each harness of the adapter folder installed here with its login, or the
// one named, proves the adapter contract at the model and effort its manifest's `[check]` names,
// in two real turns, the first writing a file and handing in done, the second, resumed, recalling
// the file.  A line per harness, then the counts; exit 1 where one failed or none is installed, 2
// where AGENTKIT_ACCEPTANCE_REQUIRED=1 and every one was skipped, else 0.  `--snapshot` is the
// usage read the windows are judged on, the host's by default; `--counts FILE`, tests/smoke.sh's
// check 3's, takes the counts and the calls made in place of the last lines and keeps each refusal
// in that snapshot.
package contract

import (
	"context"
	"fmt"
	"io"
	"os"
	"os/signal"
	"path/filepath"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/handover"
	"agentkit/internal/host"
	"agentkit/internal/run"
	"agentkit/internal/usage"
)

// Main runs `ak contract` on args, the words after it.
func Main(args []string, out, errOut io.Writer) int {
	named, snapshot, counts, read := parse(args)
	// Go runs a turn only through $AGENTKIT_ADAPTER_DIR's adapters (worker.Adapter)
	if !read || config.AdapterDir() == "" {
		return handOver(errOut)
	}
	if err := config.Check(); err != nil {
		fmt.Fprintf(errOut, "ak contract: %s\n", err)
		return 2
	}
	names := []string{named}
	if named == "" {
		names = nil
		for _, path := range config.Glob(config.AdapterDir(), "*.toml") {
			names = append(names, strings.TrimSuffix(filepath.Base(path), ".toml"))
		}
	}
	targets, carried := plan(names)
	if !carried {
		return handOver(errOut)
	}
	host.Mark("ak contract")
	// Ctrl-C takes away what the check made, as Python's KeyboardInterrupt does on its way out.
	interrupt, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	defer stop()
	// In the checkout, out of the temporary places a worker's box makes its own.
	root, err := os.MkdirTemp(config.Repo(), ".ak-test-contract-")
	if err != nil {
		fmt.Fprintf(errOut, "ak contract: %s\n", err)
		return 1
	}
	defer os.RemoveAll(root)
	if counts == "" {
		// A check on its own keeps its refusals in a snapshot of its own too.
		read := providers(snapshot)
		for _, name := range read.Keys() {
			read.Set(name, usage.WithoutPast(read.Get(name).(*run.Object), "the host cache"))
		}
		snapshot = filepath.Join(root, "usage.json")
		if err := os.WriteFile(snapshot, []byte(run.Line(run.Fields("providers", read))), 0o666); err != nil {
			fmt.Fprintf(errOut, "ak contract: %s\n", err)
			return 1
		}
	}
	tally, interrupted := check(interrupt, targets, root, snapshot, out, errOut)
	if interrupted {
		fmt.Fprintln(errOut, "\nak contract: interrupted")
		return 130
	}
	if counts != "" {
		line := fmt.Sprintf("%d %d %d %d\n", tally.passed, tally.failed, tally.skipped, tally.calls)
		if err := os.WriteFile(counts, []byte(line), 0o666); err != nil {
			fmt.Fprintf(errOut, "ak contract: %s\n", err)
			return 1
		}
	} else {
		fmt.Fprintf(out, "%d passed, %d failed, %d skipped\n", tally.passed, tally.failed, tally.skipped)
		if tally.skipped > 0 && tally.calls == 0 {
			fmt.Fprintln(out, "acceptance: INCOMPLETE; skipped coverage was not exercised")
		}
	}
	switch {
	case tally.failed > 0:
		return 1
	case tally.skipped > 0 && tally.calls == 0 && os.Getenv("AGENTKIT_ACCEPTANCE_REQUIRED") == "1":
		return 2
	}
	return 0
}

// parse is the harness args name, "" for every one, the snapshot and the counts file, and whether
// they are read as Python's argparse reads them here; any other way to write them is Python's.
func parse(args []string) (harness, snapshot, counts string, read bool) {
	snapshot = filepath.Join(config.Home(), "state", "usage.json")
	for at := 0; at < len(args); at++ {
		switch arg := args[at]; {
		case arg == "--snapshot" || arg == "--counts":
			if at++; at == len(args) || strings.HasPrefix(args[at], "-") {
				return "", "", "", false
			}
			if arg == "--snapshot" {
				snapshot = args[at]
			} else {
				counts = args[at]
			}
		case strings.HasPrefix(arg, "-") || harness != "":
			return "", "", "", false
		default:
			harness = arg
		}
	}
	return harness, snapshot, counts, true
}

// handOver leaves the whole check to Python, before anything is written.
func handOver(errOut io.Writer) int {
	fmt.Fprintln(errOut, "ak contract: not implemented in Go yet")
	return handover.Exit(handover.Here(1))
}
