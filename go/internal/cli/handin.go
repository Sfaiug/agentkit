package cli

import (
	"bufio"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"

	"agentkit/internal/config"
)

type finding struct {
	Path string `json:"path"`
	Line int    `json:"line"`
	What string `json:"what"`
}

func (f finding) site() string { return f.Path + ":" + strconv.Itoa(f.Line) }

func validateHandIn(args []string) string {
	path := os.Getenv("AK_HAND_IN")
	if path == "" || !isFile(path) {
		return "hand-in needs an active worker turn; use it from the worker's shell"
	}
	file, err := os.Open(path)
	if err != nil {
		return "cannot hand in this record: " + err.Error()
	}
	defer file.Close()
	scanner := bufio.NewScanner(file)
	scanner.Buffer(nil, int(^uint(0)>>1))
	var turn struct {
		Kind      string    `json:"kind"`
		Role      string    `json:"role"`
		Workspace *string   `json:"workspace"`
		Findings  []finding `json:"findings"`
	}
	if !scanner.Scan() {
		if err := scanner.Err(); err != nil {
			return "cannot hand in this record: " + err.Error()
		}
		return "the worker turn's record file is invalid; ask the loop to retry"
	}
	if err := json.Unmarshal(scanner.Bytes(), &turn); err != nil {
		return "cannot hand in this record: " + err.Error()
	}
	closed := false
	for scanner.Scan() {
		var row struct {
			Kind string `json:"kind"`
		}
		if err := json.Unmarshal(scanner.Bytes(), &row); err != nil {
			return "cannot hand in this record: " + err.Error()
		}
		closed = closed || contains([]string{"done", "blocked", "not-needed"}, row.Kind)
	}
	if err := scanner.Err(); err != nil {
		return "cannot hand in this record: " + err.Error()
	}
	if turn.Kind != "turn" {
		return "the worker turn's record file is invalid; ask the loop to retry"
	}
	if closed {
		return "this turn is already closed; hand in records before done, blocked or not-needed"
	}
	if turn.Workspace == nil {
		return "cannot hand in this record: 'workspace'"
	}
	if turn.Role == "" {
		turn.Role = "reviewer"
	}
	if len(args) > 0 {
		switch args[0] {
		case "blocked", "not-needed":
			if strings.HasPrefix(turn.Role, "reviewer") {
				return "blocked and not-needed are only for executor or fixer turns"
			}
			if len(args) != 2 || strings.TrimSpace(args[1]) == "" {
				return `use blocked or not-needed with one nonempty "why"`
			}
			return ""
		case "finding", "follow-up":
			if !strings.HasPrefix(turn.Role, "reviewer") {
				return "finding and follow-up are only for review turns"
			}
		case "dispute":
			if !strings.HasPrefix(turn.Role, "fixer") {
				return "dispute is only for fixer turns"
			}
		}
	}
	if len(args) == 1 && args[0] == "done" {
		return ""
	}
	var listed *finding
	if len(args) > 1 {
		for i := range turn.Findings {
			if turn.Findings[i].site() == args[1] {
				listed = &turn.Findings[i]
				break
			}
		}
	}
	start := 4
	var what, why string
	if len(args) > 0 && args[0] == "dispute" {
		if len(args) < 3 || strings.TrimSpace(args[2]) == "" {
			return `use dispute with path:line, "why it is wrong" and evidence`
		}
		if listed == nil {
			var allowed []string
			for _, item := range turn.Findings {
				allowed = append(allowed, item.site())
			}
			if len(allowed) == 0 {
				allowed = []string{"none"}
			}
			return "dispute must name a blocking finding handed to this turn; you may dispute: " + strings.Join(allowed, ", ")
		}
		start, what, why = 3, listed.What, args[2]
	} else {
		if len(args) < 4 || !contains([]string{"finding", "follow-up"}, args[0]) {
			return "use finding or follow-up with path:line, what, why it matters and evidence, dispute, or done alone"
		}
		what, why = args[2], args[3]
	}
	if strings.TrimSpace(what) == "" || strings.TrimSpace(why) == "" {
		return "supply both what is wrong and why it matters"
	}
	flags := map[string]string{}
	for i := start; i < len(args); i += 2 {
		_, duplicate := flags[args[i]]
		if !contains([]string{"--run", "--quote", "--before"}, args[i]) || duplicate || i+1 == len(args) {
			return "use one evidence flag, --run COMMAND or --quote LINES, and --before PROOF for a follow-up that predates the task"
		}
		flags[args[i]] = args[i+1]
	}
	_, run := flags["--run"]
	quote, hasQuote := flags["--quote"]
	if run == hasQuote || strings.TrimSpace(flags["--run"]+quote) == "" {
		return "supply evidence with exactly one of --run COMMAND or --quote LINES"
	}
	before, hasBefore := flags["--before"]
	if args[0] == "follow-up" {
		if hasBefore && strings.TrimSpace(before) == "" {
			return "--before names the base or an ancestor commit, or verbatim lines from the named file at base"
		}
		if !hasBefore && !run {
			return "a follow-up without --before needs --run: its command becomes the check that fixes it"
		}
	} else if hasBefore {
		return "use follow-up for a defect that existed before the task"
	}
	root := config.Absolute(*turn.Workspace)
	if err := checkedSite(args[1], root, quote, hasQuote); err != nil {
		var pathError *os.PathError
		if errors.As(err, &pathError) {
			return "cannot hand in this record: " + err.Error()
		}
		// A handed finding can name a file or line that a fix deleted. Only a
		// command can prove it again; a quote still has to exist in the checkout.
		if listed == nil || hasQuote {
			return err.Error()
		}
	}
	if command := flags["--run"]; args[0] == "follow-up" && command != "" && (!oneCommand(command) || strings.Contains(command, root)) {
		return "write a follow-up's --run as one shell command, without backticks, line breaks or this checkout's path: it becomes a plan check"
	}
	return ""
}

func checkedSite(site, root, quote string, hasQuote bool) error {
	colon := strings.LastIndexByte(site, ':')
	if colon < 1 || !digits(site[colon+1:]) {
		return fmt.Errorf("name the location as path:line with a numeric line")
	}
	name := site[:colon]
	if !filepath.IsAbs(name) {
		name = filepath.Join(root, name)
	}
	path := config.Absolute(name)
	relative, err := filepath.Rel(root, path)
	if err != nil || relative == ".." || strings.HasPrefix(relative, ".."+string(filepath.Separator)) || !isFile(path) {
		return fmt.Errorf("name a file that exists inside this checkout")
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	content := strings.ToValidUTF8(string(data), "\ufffd")
	lines := len(splitLines(content))
	line, err := strconv.Atoi(site[colon+1:])
	if err != nil || line < 1 || line > lines {
		return fmt.Errorf("choose a line from 1 to %d in %s", lines, relative)
	}
	if hasQuote && (strings.TrimSpace(quote) == "" || !strings.Contains(content, quote)) {
		return fmt.Errorf("use a quote found verbatim in the named file")
	}
	return nil
}
