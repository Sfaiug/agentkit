package harness

import (
	"cmp"
	"fmt"
	"io"
	"path/filepath"
	"slices"
	"strings"

	"agentkit/internal/config"
)

// codexWants is Codex never asking, with the whole machine, and offering no update at startup:
// versions are pinned.
var codexWants = [][2]string{{"approval_policy", `"never"`}, {"sandbox_mode", `"danger-full-access"`},
	{"check_for_update_on_startup", "false"}}

// codexYolo sets codexWants at config.toml's top level, the region above its first [table]
// header, the only one a bare key may live in, every other line kept as it is.  A key that is
// missing goes after the last one replaced, else after model_reasoning_effort, else first.
func codexYolo(out io.Writer) error {
	path := filepath.Join(config.UserHome(), ".codex", "config.toml")
	read, _, err := settings(path)
	if err != nil {
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
	if err := writeConfig(path, strings.Join(lines, "")); err != nil {
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
