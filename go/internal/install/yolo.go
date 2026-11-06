package install

import (
	"cmp"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// yolo merges ak's yolo defaults into the server's Claude and Codex settings, as install.sh's
// (a) and (b) do: a seat, or anything started by hand, never asks before it acts and never
// updates itself, everything else the owner set kept.  The adapters pass their own bypass flags
// to every run; this is for the rest.  A file that cannot be merged is left as it is, said.
func yolo(out, errOut io.Writer) error {
	home := config.UserHome()
	for _, settings := range []struct {
		path, key string
		merge     func(path string, out io.Writer) error
	}{
		{filepath.Join(home, ".claude", "settings.json"), "permissions.defaultMode", claudeYolo},
		{filepath.Join(home, ".codex", "config.toml"), "approval_policy", codexYolo},
	} {
		if err := os.MkdirAll(filepath.Dir(settings.path), 0o777); err != nil {
			return err
		}
		if err := settings.merge(settings.path, out); err != nil {
			fmt.Fprintf(errOut, "note: %v; %s left unchanged, set %s yourself\n", err, settings.path, settings.key)
		}
	}
	return nil
}

// claudeYolo has Claude bypass its permission prompts, unwarned, and never update itself: `ak
// update` is the only way a harness moves, as an update mid-run would change the thing under
// test between one round and the next, and nothing would say so.  The file is backed up first.
func claudeYolo(path string, out io.Writer) error {
	data := run.NewObject()
	raw, err := text(path)
	found := !errors.Is(err, fs.ErrNotExist)
	if found {
		if err != nil {
			return err
		}
		value, err := run.DecodeLimited([]byte(raw))
		if err != nil {
			// a malformed file is not a missing one: replacing it would drop the owner's settings
			return fmt.Errorf("%s is not valid JSON (%v)", path, err)
		}
		var object bool
		if data, object = value.(*run.Object); !object {
			return fmt.Errorf("%s is not a JSON object", path)
		}
	}
	perms, env := cmp.Or(data.Dict("permissions"), run.NewObject()), cmp.Or(data.Dict("env"), run.NewObject())
	if perms.Get("defaultMode") == "bypassPermissions" && data.Get("skipDangerousModePermissionPrompt") == true &&
		env.Get("DISABLE_AUTOUPDATER") == "1" {
		fmt.Fprintf(out, "yolo: %s already bypassPermissions, autoupdater pinned\n", path)
		return nil
	}
	if found {
		backup, err := backUp(path)
		if err != nil {
			return err
		}
		fmt.Fprintf(out, "backed up %s -> %s\n", path, backup)
	}
	perms.Set("defaultMode", "bypassPermissions")
	data.Set("permissions", perms)
	data.Set("skipDangerousModePermissionPrompt", true)
	env.Set("DISABLE_AUTOUPDATER", "1")
	data.Set("env", env)
	if err := replace(path, run.Encode(data)+"\n", 0o666); err != nil {
		return err
	}
	fmt.Fprintf(out, "yolo: %s permissions.defaultMode=bypassPermissions, skipDangerousModePermissionPrompt=true, env.DISABLE_AUTOUPDATER=1\n", path)
	return nil
}

// codexWants is Codex never asking, with the whole machine, and offering no update at startup:
// versions are pinned.
var codexWants = [][2]string{{"approval_policy", `"never"`}, {"sandbox_mode", `"danger-full-access"`},
	{"check_for_update_on_startup", "false"}}

// codexYolo sets codexWants at config.toml's top level, the region above its first [table]
// header, the only one a bare key may live in, every other line kept as it is.  A key that is
// missing goes after the last one replaced, else after model_reasoning_effort, else first.
func codexYolo(path string, out io.Writer) error {
	read, err := text(path)
	if err != nil && !errors.Is(err, fs.ErrNotExist) {
		return err
	}
	var lines []string
	seen, anchor, changed, top := map[string]bool{}, 0, false, true
	for _, line := range strings.SplitAfter(read, "\n") {
		if line == "" {
			continue
		}
		stripped := strings.TrimLeftFunc(line, config.Space)
		top = top && !strings.HasPrefix(stripped, "[")
		key, value, assigned := strings.Cut(stripped, "=")
		key = strings.Trim(strings.TrimFunc(key, config.Space), `"'`)
		at := slices.IndexFunc(codexWants, func(want [2]string) bool { return assigned && want[0] == key })
		if top && at >= 0 {
			replacement := key + " = " + codexWants[at][1] + trailingComment(value) + "\n"
			changed = changed || line != replacement
			lines = append(lines, replacement)
			seen[key] = true
			anchor = len(lines)
			continue
		}
		if top && assigned && key == "model_reasoning_effort" {
			anchor = len(lines) + 1
		}
		lines = append(lines, line)
	}
	var missing []string
	for _, want := range codexWants {
		if !seen[want[0]] {
			missing = append(missing, want[0]+" = "+want[1]+"\n")
		}
	}
	if missing != nil {
		// only a file's last line can lack its newline, and a key put straight after it would
		// be glued on: `model_reasoning_effort = "xhigh"approval_policy = "never"`
		if anchor > 0 && !strings.HasSuffix(lines[anchor-1], "\n") {
			lines[anchor-1] += "\n"
		}
		lines, changed = slices.Insert(lines, anchor, missing...), true
	}
	if !changed {
		fmt.Fprintf(out, "yolo: %s already approval_policy=never, sandbox_mode=danger-full-access\n", path)
		return nil
	}
	if err := replace(path, strings.Join(lines, ""), 0o666); err != nil {
		return err
	}
	fmt.Fprintf(out, "yolo: %s approval_policy=never, sandbox_mode=danger-full-access\n", path)
	return nil
}

// trailingComment is the `# ...` a TOML value ends with, with the spacing before it, or "": a
// key rewritten keeps what the owner wrote beside it, and a `#` in a quoted value is the value's.
func trailingComment(value string) string {
	var quote byte
	for i := 0; i < len(value); i++ {
		switch c := value[i]; {
		case quote != 0:
			if c == quote {
				quote = 0
			}
		case c == '"' || c == '\'':
			quote = c
		case c == '#':
			head := value[:i]
			return cmp.Or(head[len(strings.TrimRightFunc(head, config.Space)):], "  ") + strings.TrimRight(value[i:], "\n")
		}
	}
	return ""
}
