package harness

import (
	"cmp"
	"fmt"
	"io"
	"maps"
	"path/filepath"
	"reflect"
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
// missing goes after the last one replaced, else after model_reasoning_effort, else first.  The
// lines are read one by one, so the new file must parse to the old one with only these keys set,
// or nothing is written: a multi-line string can hold what reads as a key or a header.
func codexYolo(out io.Writer) error {
	path := filepath.Join(config.UserHome(), ".codex", "config.toml")
	read, _, err := settings(path)
	if err != nil {
		return err
	}
	before, err := config.ReadTOML(read)
	if err != nil {
		return fmt.Errorf("%s is not valid TOML (%v)", path, err)
	}
	var lines, missing []string
	seen, anchor, top := map[string]bool{}, 0, true
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
			lines = append(lines, key+" = "+codexWants[at][1]+trailingComment(value)+"\n")
			seen[key] = true
			anchor = len(lines)
			continue
		}
		if top && assigned && key == "model_reasoning_effort" {
			anchor = len(lines) + 1
		}
		lines = append(lines, line)
	}
	var wanted strings.Builder
	for _, want := range codexWants {
		wanted.WriteString(want[0] + " = " + want[1] + "\n")
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
		lines = slices.Insert(lines, anchor, missing...)
	}
	text := strings.Join(lines, "")
	set, _ := config.ReadTOML(wanted.String())
	maps.Copy(before, set)
	if after, err := config.ReadTOML(text); err != nil || !reflect.DeepEqual(after, before) {
		return fmt.Errorf("%s: setting its top-level keys line by line would change more, so nothing was changed", path)
	}
	if text == read {
		fmt.Fprintf(out, "yolo: %s already approval_policy=never, sandbox_mode=danger-full-access\n", path)
		return nil
	}
	if err := writeConfig(path, text); err != nil {
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
