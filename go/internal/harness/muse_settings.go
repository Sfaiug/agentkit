package harness

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/lock"
	"agentkit/internal/run"
)

func init() {
	verbs["muse hooks"] = museHooks
}

// museEvents are the events a seat's Muse hooks, as its own schema names them, asked under env: none
// where it names no notification event, as an older one refuses settings it does not know and its
// seat is read off the screen alone.
func museEvents(program string, env []string) []string {
	schema, err := os.MkdirTemp("", "ak-muse-schema-")
	if err != nil {
		return nil
	}
	defer os.RemoveAll(schema)
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	probe := exec.CommandContext(ctx, Binary(program), "schema", "generate-json-schema", "--out", schema)
	probe.Env = env
	if probe.Run() != nil {
		return nil
	}
	files, _ := filepath.Glob(filepath.Join(schema, "*.json"))
	for _, file := range files {
		if data, _ := os.ReadFile(file); bytes.Contains(data, []byte(`"notification"`)) {
			return []string{"SessionStart", "Stop", "Notification", "PostToolBatch", "Interrupt"}
		}
	}
	return nil
}

// museAsync is whether Muse goes on past that event's hook: it runs an Interrupt one only alongside
// the turn, and a PostToolBatch one, run on every tool batch, need not hold it up.
func museAsync(event string) bool {
	return event == "PostToolBatch" || event == "Interrupt"
}

// museHooks is muse.sh `hooks`: the events a seat's launch hooks, merged into the settings file
// of the login it names, for the sessions `/new` opens (museWire).
func museHooks(_ []string, out, errOut io.Writer) int {
	events := museEvents("muse", nil)
	if events == nil {
		fmt.Fprintln(out, "muse: no muse here runs hooks; its seats are read off the screen")
		return 0
	}
	path, err := museWire(museConfig(os.Getenv("AGENTKIT_ACCOUNT")), events)
	if err != nil {
		fmt.Fprintln(errOut, "muse:", err)
		return 1
	}
	fmt.Fprintf(out, "muse: hooks.%s -> %s in %s\n", strings.Join(events, "/"), museAdapter(), path)
	return 0
}

// museAdapter is the adapter stub of the checkout this program runs from, whose `hook` hands over to it.
func museAdapter() string {
	self, _ := os.Executable()
	return filepath.Join(filepath.Dir(filepath.Dir(self)), "adapters", "muse.sh")
}

// museWire is muse.sh `wire`, into the settings file of the config home given: Muse 1.4.20 runs a
// launch line's hooks in that launch's own session alone, each event's in place of the settings
// file's, and a session `/new` opens runs the file's, read as it opens.  So the file carries the
// same events, merged in beside whatever it holds: an adapters/muse.sh's own hooks there, this
// checkout's or another's, Python's or Go's, give way to this one's, and an event no longer hooked
// keeps none of them.  `exec`, so the hook's parent is that Muse.  Written whole under Muse's own
// lock (museHome), where a link leads, though its file is not there yet: a session opening
// meanwhile reads one file or the other.  A file not of Muse's shape is left as it is.
func museWire(home string, events []string) (string, error) {
	dir := filepath.Join(home, "muse")
	path, locked := filepath.Join(dir, "settings.json"), filepath.Join(dir, ".settings.json.lock")
	// a login's links lead into the owner's folder, which may not be there yet
	for _, folder := range []string{dir, filepath.Dir(config.Resolve(locked)),
		filepath.Dir(config.Resolve(path))} {
		if err := os.MkdirAll(folder, 0o777); err != nil {
			return "", err
		}
	}
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	held, err := lock.Wait(ctx, locked)
	if err != nil {
		return "", err
	}
	defer held.Close()
	real := config.Resolve(path)
	had := run.NewObject()
	if data, err := os.ReadFile(real); err == nil {
		read, err := run.Decode(data)
		if had, _ = read.(*run.Object); err != nil || had == nil {
			return "", errors.New(path + " is not a JSON object; left as it is")
		}
	} else if !errors.Is(err, fs.ErrNotExist) {
		return "", err
	}
	// `"hooks": null` is no hooks, as Muse reads it
	theirs, read := had.Get("hooks").(*run.Object)
	if !read && had.Get("hooks") != nil {
		return "", errors.New(path + " is not settings of Muse's shape; left as it is")
	}
	hooks := run.NewObject()
	if read {
		for _, event := range theirs.Keys() {
			kept, read := museTheirs(theirs.Get(event))
			if !read {
				return "", errors.New(path + " is not settings of Muse's shape; left as it is")
			}
			if len(kept) > 0 {
				hooks.Set(event, kept)
			}
		}
	}
	command := "exec bash " + commandhelp.ShellJoin([]string{museAdapter()}) + " hook"
	for _, event := range events {
		entry := run.Fields("type", "command", "command", command)
		if museAsync(event) {
			entry.Set("async", true)
		}
		groups, _ := hooks.Get(event).([]any)
		hooks.Set(event, append(groups, run.Fields("hooks", []any{entry})))
	}
	merged := run.Fields("schema_version", run.Number("1")) // Muse refuses a file without one
	for _, key := range had.Keys() {
		merged.Set(key, had.Get(key))
	}
	if merged.Set("hooks", hooks); run.Equal(merged, had) {
		return path, nil
	}
	tmp, err := os.CreateTemp(filepath.Dir(real), ".settings.json.")
	if err != nil {
		return "", err
	}
	defer os.Remove(tmp.Name())
	if info, err := os.Stat(real); err == nil {
		tmp.Chmod(info.Mode().Perm())
	}
	_, err = tmp.WriteString(run.EncodeText(merged) + "\n")
	if closed := tmp.Close(); err == nil {
		err = closed
	}
	if err != nil {
		return "", err
	}
	return path, os.Rename(tmp.Name(), real)
}

// museTheirs is an event's groups without an adapters/muse.sh's own hooks (museOurs), a group left
// with none gone, and whether they read as Muse's: a list of groups, each an object holding a list.
func museTheirs(value any) ([]any, bool) {
	groups, read := value.([]any)
	kept := []any{}
	for _, each := range groups {
		group, _ := each.(*run.Object)
		if group == nil {
			return nil, false
		}
		hooks, listed := group.Get("hooks").([]any)
		if !listed {
			return nil, false
		}
		left := []any{}
		for _, hook := range hooks {
			if entry, _ := hook.(*run.Object); entry == nil || !museOurs(entry.Str("command")) {
				left = append(left, hook)
			}
		}
		if len(left) > 0 {
			group = group.Copy()
			group.Set("hooks", left)
			kept = append(kept, group)
		}
	}
	return kept, read
}

// museOurs is whether a hook's command is an adapters/muse.sh's own, of any checkout: `exec bash
// <it> hook`, or `call`.
func museOurs(command string) bool {
	words, read := commandhelp.ShellSplit(command)
	return read && len(words) == 4 && words[0] == "exec" && words[1] == "bash" &&
		strings.HasSuffix(words[2], "/adapters/muse.sh") && (words[3] == "hook" || words[3] == "call")
}
