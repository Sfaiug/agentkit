package handback

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"unicode/utf8"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// handbackLine is Python's handback_line: every ending uses its decision or delivery line.
// A shortened notice is saved whole before any keys are sent, under Give's delivery lock.
func handbackLine(record *run.Object, dir string, save bool) string {
	word, why, move, detail := Decision(record, dir, run.Delivery(record, run.Models()))
	if move != "" {
		whole := run.Decision(record, dir, word, sentences(why, utf8.RuneCountInString(why)+1), move+detail, false)
		if line, err := DecisionLine(record, dir, word, why, move, detail); err == nil && (line == whole || !save || saveNotice(dir, record, whole)) {
			return line
		}
		return ""
	}
	workspace := ""
	if record.Truthy("scratch") && record.Truthy("worktree") {
		workspace = " Workspace: " + record.Str("worktree") + "."
	}
	ending := "run " + filepath.Base(dir) + " finished " + word
	whole := fmt.Sprintf("%s: %s. Result: %s.%s Decide the next step.", ending, why, filepath.Join(dir, "result.md"), workspace)
	if fits(whole) {
		return whole
	}
	parts := []string{ending + ".", "Result: " + shortPath(filepath.Join(dir, "result.md")) + "."}
	if count := len(record.List("followups")); count > 0 {
		parts = append(parts, fmt.Sprintf("%d review follow-ups in full in result.md.", count))
	}
	line := strings.Join(append(parts, "Decide the next step."), " ")
	if fits(line) && (!save || saveNotice(dir, record, whole)) {
		return line
	}
	return ""
}

// DecisionLine is the line a decision is told in, Python's decision without its save: `why` in
// whole sentences within a typed line's bounds, the move's detail dropped first, then `why` for
// a pointer to the result; an error where not even that fits.
func DecisionLine(record *run.Object, dir, word, why, move, detail string) (string, error) {
	most := min(decisionMost, int(config.Longest()))
	for _, step := range [][2]string{{move + detail, why}, {move, why}, {move, "The result says why."}} {
		frame := run.Decision(record, dir, word, "x", step[0], false)
		if said := sentences(step[1], most-utf8.RuneCountInString(frame)+len("x.")); said != "" {
			if line := run.Decision(record, dir, word, said, step[0], false); fits(line) {
				return line, nil
			}
		}
	}
	return "", fmt.Errorf("run %s's decision line has no room for a reason in %d characters", filepath.Base(dir), most)
}

func fits(line string) bool {
	return !config.TooLong(line)
}

// sentences keeps leading whole sentences, counting characters as Python's terminal.sentences.
func sentences(text string, room int) string {
	text = config.Fold(text)
	if text != "" && !strings.ContainsAny(text[len(text)-1:], ".!?") {
		text += "."
	}
	if utf8.RuneCountInString(text) <= room {
		return text
	}
	runes, end := []rune(text), 0
	for i := 0; i < min(max(room, 0), len(runes)-1); i++ {
		if strings.ContainsRune(".!?", runes[i]) && runes[i+1] == ' ' {
			end = i + 1
		}
	}
	return string(runes[:end])
}

func shortPath(path string) string {
	if home, err := os.UserHomeDir(); err == nil {
		if rest, err := filepath.Rel(home, path); err == nil && rest != ".." && !strings.HasPrefix(rest, ".."+string(filepath.Separator)) {
			return "~/" + rest
		}
	}
	return path
}

func saveNotice(dir string, record *run.Object, whole string) bool {
	path := filepath.Join(dir, "result.md")
	saved, err := os.ReadFile(path)
	if err != nil && !os.IsNotExist(err) {
		return false
	}
	_, kept, _ := strings.Cut(string(saved), "\n## Seat notice\n\n")
	parts := []string{whole}
	if followups := record.List("followups"); len(followups) > 0 {
		lines := []string{"## Follow-ups", ""}
		for _, item := range followups {
			lines = append(lines, "- "+strings.ReplaceAll(run.Text(item), "\n", "\n  "))
		}
		parts = append(parts, strings.Join(lines, "\n")+"\n")
	}
	parts = append(parts, FollowupReport(record))
	var missing []string
	for _, part := range parts {
		if part != "" && !strings.Contains(kept, part) {
			missing = append(missing, part)
		}
	}
	if len(missing) == 0 {
		return true
	}
	return os.WriteFile(path, append(saved, []byte("\n## Seat notice\n\n"+strings.Join(missing, "\n\n")+"\n")...), 0o666) == nil
}
