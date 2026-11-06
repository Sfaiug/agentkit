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

// codexYolo sets codexWants in config.toml's own table, above its first [table] header, every
// other byte kept.  A key set there is rewritten on the lines its statement fills, the comment
// beside it kept; one missing goes after the last such statement or model_reasoning_effort's,
// else first.  The new file must read as the old one with only these keys set, or nothing is
// written: an approval_policy table of the owner's would meet ak's string.
func codexYolo(out io.Writer) error {
	path := filepath.Join(config.UserHome(), ".codex", "config.toml")
	read, _, err := settings(path)
	if err != nil {
		return err
	}
	before, err := config.ReadTOML(read)
	var top []config.TOMLSet
	if err == nil {
		top, err = config.TOMLTop(read)
	}
	if err != nil {
		return fmt.Errorf("%s is not valid TOML (%v)", path, err)
	}
	var text, wanted strings.Builder
	seen, done, anchor := map[string]bool{}, 0, 0
	for _, set := range top {
		// the statement's last line, its newline included: no other statement shares it
		end := len(read)
		if i := strings.IndexByte(read[set.End:], '\n'); i >= 0 {
			end = set.End + i + 1
		}
		key := strings.Join(set.Key, ".")
		at := slices.IndexFunc(codexWants, func(want [2]string) bool { return len(set.Key) == 1 && want[0] == key })
		if at >= 0 {
			text.WriteString(read[done : strings.LastIndexByte(read[:set.Start], '\n')+1])
			text.WriteString(key + " = " + codexWants[at][1] + trailingComment(read[set.End:end]) + "\n")
			done, seen[key] = end, true
		}
		if at >= 0 || key == "model_reasoning_effort" {
			anchor = end
		}
	}
	text.WriteString(read[done:anchor])
	for _, want := range codexWants {
		wanted.WriteString(want[0] + " = " + want[1] + "\n")
		if seen[want[0]] {
			continue
		}
		// only a file's last line can lack its newline, and a key put straight after it would
		// be glued on: `model_reasoning_effort = "xhigh"approval_policy = "never"`
		if anchor > 0 && !strings.HasSuffix(text.String(), "\n") {
			text.WriteString("\n")
		}
		text.WriteString(want[0] + " = " + want[1] + "\n")
	}
	text.WriteString(read[anchor:])
	ours, _ := config.ReadTOML(wanted.String())
	maps.Copy(before, ours)
	if after, err := config.ReadTOML(text.String()); err != nil || !reflect.DeepEqual(after, before) {
		return fmt.Errorf("merging ak's keys would change more of %s than them, so nothing was changed", path)
	}
	if text.String() == read {
		fmt.Fprintf(out, "yolo: %s already approval_policy=never, sandbox_mode=danger-full-access\n", path)
		return nil
	}
	if err := writeConfig(path, text.String()); err != nil {
		return err
	}
	fmt.Fprintf(out, "yolo: %s approval_policy=never, sandbox_mode=danger-full-access\n", path)
	return nil
}

// trailingComment is the comment on the rest of a value's line, with the space before it, or "":
// a key rewritten keeps what the owner wrote beside it.
func trailingComment(rest string) string {
	at := strings.IndexByte(rest, '#')
	if at < 0 {
		return ""
	}
	return cmp.Or(rest[:at], "  ") + strings.TrimRight(rest[at:], "\n")
}
