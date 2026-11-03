package loop

import (
	"cmp"
	"context"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"

	"agentkit/internal/config"
	"agentkit/internal/lock"
	"agentkit/internal/run"
	"agentkit/internal/task"
)

var (
	stoppedLine = regexp.MustCompile(`^\[\d\d:\d\d:\d\d\] done-when: stopped `)
	aside       = regexp.MustCompile(`(?mi)^(#+)[ \t]*(?:Follow-ups|Notes)\b[^\n]*$`)
)

// WriteResult is result.md for the run at dir as its record stands, under the delivery lock,
// Python's record_result: the full report where there is a workspace to report on, else the
// reason and the relaunch.
func WriteResult(dir string, record *run.Object) error {
	suffix := ""
	if fullResult(record) {
		_, cmds, err := task.Read(filepath.Join(dir, "task.md"))
		if err == nil {
			return save(dir, report(dir, record, declaredChecks(record, cmds)))
		}
		suffix = "\n\n(the full result could not be written: " + err.Error() + ")"
	}
	return save(dir, fmt.Sprintf("# %s — %s\n\nVERDICT: %s\n\n## Why this run stopped\n\n%s\n\nrelaunch: %s%s\n\n",
		run.Delivery(record, nil), cmp.Or(record.Str("title"), filepath.Base(dir)), cmp.Or(record.Str("verdict"), "none"),
		cmp.Or(record.Str("error"), "no reason was recorded"), run.Relaunch(dir, record), suffix))
}

// fullResult is whether a run has a workspace to report on, and a review a verdict.
func fullResult(record *run.Object) bool {
	return record.Truthy("worktree") && record.Has("round_summaries") && (!record.Truthy("review_pr") || record.Truthy("verdict"))
}

func save(dir, text string) error {
	delivery, err := lock.Wait(context.Background(), filepath.Join(dir, "delivery.lock"))
	if err != nil {
		return err
	}
	defer delivery.Close()
	return os.WriteFile(filepath.Join(dir, "result.md"), []byte(text), 0o666)
}

// report is the full result.md, Python's handback.write_result, its opening the workplace's.  A run
// that ends well lists the checks its rounds ran, without their `# once` marks; any other lists the
// task's.
func report(dir string, record *run.Object, cmds []string) string {
	outcome := run.Delivery(record, run.Models())
	if record.Str("state") == "blocked" {
		outcome = "BLOCKED"
	}
	spent := record.List("round_summaries")
	parts := append([]string{"# " + outcome + " — " + record.Str("title"), "", "VERDICT: " + run.Field(record, "verdict", "None"),
		"rounds: " + strconv.Itoa(len(spent)) + " of " + run.Field(record, "rounds", "None")}, placeOf(record).head(dir, record)...)
	if record.Truthy("blocked") {
		parts = append(parts, "", record.Str("blocked"), "")
	}
	once := false
	shown := make([]string, len(cmds))
	for i, cmd := range cmds {
		bare, marked := task.SplitOnce(cmd)
		switch {
		case !marked:
			shown[i] = cmd
		case record.Str("state") == "pass":
			shown[i] = bare
		default:
			shown[i], once = bare+" (once)", true
		}
	}
	final := "final check: none (no once-commands)"
	if once {
		final = "final check: not run"
	}
	parts = append(parts, "", "## Done-when", "```", strings.Join(shown, "\n"), "```", "", final, "")
	if line := baseProofLine(record); line != "" {
		parts = append(parts, line, "")
	}
	if log, err := os.ReadFile(filepath.Join(dir, "log.txt")); err == nil {
		var stopped []string
		for _, line := range config.SplitLines(decoded(log)) {
			if stoppedLine.MatchString(line) {
				_, said, _ := strings.Cut(line, "] ")
				stopped = append(stopped, strings.TrimRightFunc(said, config.Space))
			}
		}
		if len(stopped) > 0 {
			parts = append(append(append(parts, "## Stopped checks", "", "```"), stopped...), "```", "")
		}
	}
	for _, each := range spent {
		entry, _ := each.(*run.Object)
		if entry == nil {
			continue
		}
		checked := "done-when not run"
		switch entry.Get("done_when") {
		case true:
			checked = "done-when passed"
		case false:
			checked = "done-when failed"
		}
		parts = append(parts, fmt.Sprintf("## Round %s (%s, %s)", run.Text(entry.Get("round")), entry.Str("verdict"), checked), "", entry.Str("summary"), "")
	}
	why := cmp.Or(record.Str("error"), record.Str("interruption_reason"))
	if why == "" && record.Str("verdict") != "PASS" {
		why = failedCheck(record)
	}
	if why != "" {
		parts = append(parts, "## Why this run stopped", "", why, "")
	}
	if review := record.Dict("review"); review != nil && review.Truthy("overridden") && record.Str("verdict") != "PASS" {
		parts = append(parts, "## Overridden to FAIL\n"+review.Str("overridden")+"\n\n")
	}
	if record.Str("verdict") != "PASS" && record.Truthy("findings") {
		parts = append(parts, "## Reviewer findings", "", withoutAsides(record.Str("findings")), "")
		if record.Truthy("findings_file") {
			parts = append(parts, "Every one in full: "+record.Str("findings_file"), "")
		}
	}
	for _, section := range [][2]string{{"followups", "Follow-ups"}, {"notes", "Notes"}, {"disputes", "Disputes"}} {
		if items := record.List(section[0]); len(items) > 0 {
			parts = append(parts, "## "+section[1], "")
			for _, item := range items {
				parts = append(parts, "- "+strings.ReplaceAll(run.Text(item), "\n", "\n  "))
			}
			parts = append(parts, "")
			if section[0] == "followups" {
				parts = append(parts, "") // Python's followup_report closes its own block too
			}
		}
	}
	if onward := run.ContinueLine(record, dir, time.Now()); onward != "" {
		parts = append(parts, onward, "")
	}
	return strings.Join(parts, "\n")
}

// failedCheck is the check a FAIL still has failing, "" for none, as Python's failed_check says it
// of a round's own done-when.
func failedCheck(record *run.Object) string {
	if history := record.Dict("done_when_failure"); history != nil {
		if failing := history.List("every"); len(failing) > 0 {
			return "the done-when failed: " + checkLine(failing[0])
		}
	}
	return ""
}

// withoutAsides is a review without its follow-ups and notes, Python's prompts.without_followups:
// each section ends at the next heading of its level or higher.
func withoutAsides(text string) string {
	for at := aside.FindStringSubmatchIndex(text); at != nil; at = aside.FindStringSubmatchIndex(text) {
		level := at[3] - at[2]
		section := text[at[1]:]
		end := regexp.MustCompile(fmt.Sprintf(`(?m)^#{1,%d}[ \t]`, level)).FindStringIndex(section)
		if end == nil {
			text = text[:at[0]]
		} else {
			text = text[:at[0]] + section[end[0]:]
		}
	}
	return text
}

// links is every file in the workspace as a link to it, uncapped, Python's gitcall.links: the
// destination is percent-encoded, the few characters that would end the text early are escaped,
// and a control character is shown encoded, as a line break would end the link.
func links(root string) string {
	var rows []string
	for _, relative := range files(root) {
		var text strings.Builder
		for name := relative; name != ""; {
			r, size := utf8.DecodeRuneInString(name)
			switch {
			case r == utf8.RuneError && size == 1, !unicode.IsPrint(r):
				text.WriteString(escaped(name[:size]))
			case strings.ContainsRune("\\[]`<", r):
				text.WriteString(`\` + string(r))
			default:
				text.WriteRune(r)
			}
			name = name[size:]
		}
		rows = append(rows, fmt.Sprintf("- [%s](%s)", text.String(), escaped(filepath.Join(root, relative))))
	}
	if len(rows) == 0 {
		return "(the workspace is empty)"
	}
	return strings.Join(rows, "\n")
}

// escaped is a path percent-encoded as Python's urllib.parse.quote: its slashes and the unreserved
// characters as they are, any other byte as its code.
func escaped(path string) string {
	var out strings.Builder
	for i := 0; i < len(path); i++ {
		if c := path[i]; c < utf8.RuneSelf && (unicode.IsLetter(rune(c)) || unicode.IsDigit(rune(c)) || strings.IndexByte("_.-~/", c) >= 0) {
			out.WriteByte(c)
		} else {
			fmt.Fprintf(&out, "%%%02X", c)
		}
	}
	return out.String()
}
