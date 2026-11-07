package cli

import (
	"cmp"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"time"

	"agentkit/internal/gitcall"
	"agentkit/internal/history"
	"agentkit/internal/menu"
	"agentkit/internal/suitetimes"
	"agentkit/internal/terminal"
)

var auditHeads = []string{"test", "time", "flakes", "catches", "main red", "proposal"}

// An audited test file is its row's cells and its seconds, -1 where none were kept.
type audited struct {
	cells   []string
	seconds float64
}

// testAudit is `ak run status --tests`, Python's status.tests_status: each test file of this
// checkout with the seconds its suite's pieces last printed and its outcomes in history.db, read
// as they stand.  It runs no suite and changes no file; it only proposes.
func testAudit(out, errOut io.Writer) int {
	cwd, err := os.Getwd()
	if err != nil {
		return notImplemented(errOut, "run status")
	}
	top, err := gitcall.Git{Repo: cwd}.Must("rev-parse", "--show-toplevel")
	if err != nil {
		fmt.Fprintf(errOut, "ak run: %s\n", err)
		return 2
	}
	name := filepath.Base(top)
	times := suitetimes.Read(top)
	audit, err := history.TestAudit(name)
	if err != nil {
		return notImplemented(errOut, "run status")
	}
	tests := map[string]bool{}
	for test := range times {
		tests[test] = true
	}
	for test := range audit.Reds {
		tests[test] = true
	}
	var rows []audited
	for test := range tests {
		count := func(column string) int64 {
			n, _ := audit.Reds[test].Num(column)
			return int64(n)
		}
		flakes, catches := count("flakes"), count("catches")
		seconds, timed := times[test]
		shown, proposals := "–", []string{}
		if timed {
			shown = fmt.Sprintf("%.1fs", seconds)
			if seconds > audit.Target {
				proposals = append(proposals, "split")
			}
		} else {
			seconds = -1
		}
		if flakes > 0 && catches == 0 {
			proposals = append(proposals, "fix or delete")
		}
		rows = append(rows, audited{[]string{test, shown, strconv.FormatInt(flakes, 10),
			strconv.FormatInt(catches, 10), strconv.FormatInt(count("main_red"), 10),
			strings.Join(proposals, "; ")}, seconds})
	}
	// proposals first, then the slowest, the untimed last
	slices.SortFunc(rows, func(a, b audited) int {
		return cmp.Or(cmp.Compare(quiet(a), quiet(b)), cmp.Compare(b.seconds, a.seconds),
			strings.Compare(a.cells[0], b.cells[0]))
	})
	screen := terminal.For(out)
	room := screen.LayoutWidth()
	widths, used := make([]int, len(auditHeads)), 10
	for i, head := range auditHeads {
		widths[i] = terminal.Cells(head)
		for _, row := range rows {
			widths[i] = max(widths[i], terminal.Cells(row.cells[i]))
		}
		if i > 0 {
			used += widths[i]
		}
	}
	widths[0] = max(1, room-used)
	narrow := room < 60 || widths[0] < 10
	var lines []string
	if !narrow {
		lines = append(lines, screen.TableRow(auditHeads, widths, slices.Repeat([]string{"dim"}, len(auditHeads))))
	}
	for _, row := range rows {
		if narrow {
			lines = append(lines, terminal.Wrap(row.cells[0], room)...)
			detail := fmt.Sprintf("%s  %s flakes  %s catches  %s main red", row.cells[1], row.cells[2], row.cells[3], row.cells[4])
			if row.cells[5] != "" {
				detail += "  " + row.cells[5]
			}
			for _, line := range terminal.Wrap(detail, room-2) {
				lines = append(lines, "  "+line)
			}
			continue
		}
		for i, test := range terminal.Wrap(row.cells[0], widths[0]) {
			rest := row.cells[1:]
			if i > 0 {
				rest = make([]string, len(rest))
			}
			lines = append(lines, screen.TableRow(append([]string{test}, rest...), widths, nil))
		}
	}
	summary := fmt.Sprintf("%s tests: %d files, %.1f days of rows", name, len(rows), audit.Days)
	clock := time.Now().Format("15:04")
	// the header's name gives way to its clock: one cut there opens the body too
	if !strings.Contains(menu.Panel(screen, summary, clock, nil, "")[0], summary) {
		lines = append(terminal.Wrap(summary, room), lines...)
	}
	for _, line := range menu.Panel(screen, summary, clock, lines, "") {
		fmt.Fprintln(out, line)
	}
	return 0
}

// quiet is 1 for a file with nothing proposed, which sorts after those with something.
func quiet(row audited) int {
	if row.cells[5] == "" {
		return 1
	}
	return 0
}
