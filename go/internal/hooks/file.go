package hooks

import (
	"fmt"
	"io"
	"os"
	"path/filepath"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/run"
	"agentkit/internal/task"
)

// write puts the table's scripts, under root's hooks/, in its settings file, a file of ak's own,
// as the Python adapter's heredoc does: one already holding them is left alone, and one that
// differs, readable or not, moved to the day's backup first.  It answers the exit code: 0
// written or already there, 1 where the heredoc ends in a traceback.
func write(table config.HookTable, root string, out, errOut io.Writer) int {
	path, whole := table.Settings, document(table, root)
	if err := os.MkdirAll(filepath.Dir(path), 0o777); err != nil {
		fmt.Fprintln(errOut, err)
		return 1
	}
	// as Python's json.load reads a text file, so only a file that means the same is left alone
	if raw, err := os.ReadFile(path); err == nil {
		if read, err := run.Decode([]byte(task.Text(raw))); err == nil && run.Equal(read, whole) {
			fmt.Fprintf(out, "hooks: %s already installed, running %s\n", path, runs(table, root))
			return 0
		}
	}
	if _, err := os.Stat(path); err == nil {
		backup := path + ".bak-" + time.Now().Format("20060102")
		if err := os.Rename(path, backup); err != nil {
			fmt.Fprintln(errOut, err)
			return 1
		}
		fmt.Fprintf(out, "backed up %s -> %s\n", path, backup)
	}
	if err := os.WriteFile(path, []byte(run.Encode(whole)+"\n"), 0o666); err != nil {
		fmt.Fprintln(errOut, err)
		return 1
	}
	fmt.Fprintf(out, "hooks: %s now runs %s\n", path, runs(table, root))
	return 0
}

// document is the whole file: under "hooks", each event's one group, its matcher where it has
// one, holding each of its scripts' entries.
func document(table config.HookTable, root string) *run.Object {
	hooks := run.NewObject()
	for _, event := range table.Events {
		group, entries := run.NewObject(), []any{}
		if event.Matcher != "" {
			group.Set("matcher", event.Matcher)
		}
		for _, script := range event.Scripts {
			entries = append(entries, wanted(event, root, script))
		}
		group.Set("hooks", entries)
		hooks.Set(event.Name, []any{group})
	}
	whole := run.NewObject()
	whole.Set("hooks", hooks)
	return whole
}
