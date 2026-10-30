// Package hooks merges ak's hook scripts into a harness's settings file as its manifest's
// `[hooks.install]` table says, keeping everything else the file holds.  It hides which
// entries are ak's (a command naming one of a script's names), their repointing (every one
// found, duplicates included, so a checkout that moved leaves nothing calling a file no longer
// there), the splitting of a group another tool's handlers share where an event wants its own
// matcher, the backup made before a file first changes, and the refusals of a file it could
// not merge into without losing what is there.
package hooks

import (
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// A handler is one entry of ours and the group it sits in.
type handler struct{ group, entry *run.Object }

// Install wires the table's scripts, under root's hooks/, into its settings file, and answers
// the exit code: 0 wired, 1 a file refused or not written, 2 a directory that cannot be made.
func Install(table config.HookTable, root string, out, errOut io.Writer) int {
	path := table.Settings
	if err := os.MkdirAll(filepath.Dir(path), 0o777); err != nil {
		fmt.Fprintln(errOut, err)
		return 2
	}
	raw, err := os.ReadFile(path)
	missing := errors.Is(err, fs.ErrNotExist)
	if err != nil && !missing {
		fmt.Fprintf(errOut, "cannot read %s: %v\n", path, err)
		return 1
	}
	data := run.NewObject()
	if !missing {
		read, err := run.Decode(raw)
		if err != nil {
			// a malformed file is not a missing one: replacing it would drop the owner's settings
			fmt.Fprintf(errOut, "%s is not valid JSON (%v); left alone\n", path, err)
			return 1
		}
		if data, _ = read.(*run.Object); data == nil {
			fmt.Fprintf(errOut, "%s is not a JSON object; left alone\n", path)
			return 1
		}
	}
	hooks, _ := data.Get("hooks").(*run.Object)
	if hooks == nil {
		hooks = run.NewObject()
	}
	// read before anything changes: wired, the file stays exactly as it is
	if wired(table, hooks, root) {
		fmt.Fprintf(out, "hooks: %s already runs %s\n", path, runs(table, root))
		return 0
	}
	if !missing {
		backup := path + ".bak-" + time.Now().Format("20060102")
		if err := backUp(path, backup, raw); err != nil {
			fmt.Fprintln(errOut, err)
			return 1
		}
		fmt.Fprintf(out, "backed up %s -> %s\n", path, backup)
	}
	for _, event := range table.Events {
		read := hooks.List(event.Name)
		groups := slices.Clone(read)
		for _, script := range event.Scripts {
			found := ours(read, table.Names[script])
			if len(found) == 0 {
				group, entry := run.NewObject(), run.NewObject()
				group.Set("hooks", []any{entry})
				groups = append(groups, group)
				found = []handler{{group, entry}}
			}
			for _, each := range found {
				group, want := each.group, wanted(event, root, script)
				for _, key := range want.Keys() {
					each.entry.Set(key, want.Get(key))
				}
				if event.Matcher == "" || group.Str("matcher") == event.Matcher {
					continue
				}
				if others := group.List("hooks"); len(others) > 1 { // the others keep the tools they run for
					others = slices.DeleteFunc(slices.Clone(others), func(other any) bool { return other == any(each.entry) })
					group.Set("hooks", others)
					group = run.NewObject()
					group.Set("hooks", []any{each.entry})
					groups = append(groups, group)
				}
				group.Set("matcher", event.Matcher)
			}
		}
		hooks.Set(event.Name, groups)
	}
	data.Set("hooks", hooks)
	tmp := path + ".ak-tmp"
	if err := os.WriteFile(tmp, []byte(run.Encode(data)+"\n"), 0o666); err != nil {
		fmt.Fprintln(errOut, err)
		return 1
	}
	if err := os.Rename(tmp, path); err != nil {
		fmt.Fprintln(errOut, err)
		return 1
	}
	fmt.Fprintf(out, "hooks: %s now runs %s\n", path, runs(table, root))
	return 0
}

// wired is whether each script has exactly one entry of ours on each of its events, holding
// what it wants under the event's matcher.
func wired(table config.HookTable, hooks *run.Object, root string) bool {
	for _, event := range table.Events {
		for _, script := range event.Scripts {
			found := ours(hooks.List(event.Name), table.Names[script])
			if len(found) != 1 || event.Matcher != "" && found[0].group.Str("matcher") != event.Matcher {
				return false
			}
			want := wanted(event, root, script)
			for _, key := range want.Keys() {
				if !run.Equal(found[0].entry.Get(key), want.Get(key)) {
					return false
				}
			}
		}
	}
	return true
}

// ours is each entry among an event's groups whose command is a string naming one of names.
func ours(groups []any, names []string) (found []handler) {
	for _, each := range groups {
		group, _ := each.(*run.Object)
		if group == nil {
			continue
		}
		for _, item := range group.List("hooks") {
			entry, _ := item.(*run.Object)
			if entry == nil {
				continue
			}
			command, _ := entry.Get("command").(string)
			if slices.ContainsFunc(names, func(name string) bool { return strings.Contains(command, name) }) {
				found = append(found, handler{group, entry})
			}
		}
	}
	return found
}

// wanted is what an entry of ours holds: the script run as a command, in the background where
// the event is only heard.
func wanted(event config.HookEvent, root, script string) *run.Object {
	entry := run.NewObject()
	entry.Set("type", "command")
	entry.Set("command", command(root, script))
	if event.Heard {
		entry.Set("async", true)
	}
	return entry
}

// command runs the script under the root it was given, never resolved, as the Python adapter
// writes it for the same checkout.
func command(root, script string) string {
	return "bash " + root + "/hooks/" + script
}

// runs says each script's command and the events it runs on.
func runs(table config.HookTable, root string) string {
	var scripts []string
	on := map[string][]string{}
	for _, event := range table.Events {
		for _, script := range event.Scripts {
			if on[script] == nil {
				scripts = append(scripts, script)
			}
			on[script] = append(on[script], event.Name)
		}
	}
	said := make([]string, len(scripts))
	for i, script := range scripts {
		said[i] = command(root, script) + " on " + strings.Join(on[script], ", ")
	}
	return strings.Join(said, "; ")
}

// backUp copies the file's bytes, mode and modification time to backup, as Python's copy2 does.
func backUp(path, backup string, raw []byte) error {
	info, err := os.Stat(path)
	if err != nil {
		return err
	}
	if err := os.WriteFile(backup, raw, info.Mode()); err != nil {
		return err
	}
	if err := os.Chmod(backup, info.Mode()); err != nil {
		return err
	}
	return os.Chtimes(backup, time.Time{}, info.ModTime())
}
