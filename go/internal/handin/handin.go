// Package handin owns a worker turn's record file, the one $AK_HAND_IN names: the loop opens it
// with the turn's row, and each `ak hand-in` appends one row.  It hides what each role may hand
// in, the site and evidence checks, a proof's run and its excerpt, the lock held from the first
// read to the append, and the row appended, as Python's json.dumps(row) writes it.  Hand decides
// in Python's hand_in.main order; what Go cannot do as Python does is ErrPython.
package handin

import (
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"syscall"
	"unicode"
	"unicode/utf8"

	"agentkit/internal/config"
	"agentkit/internal/lock"
	"agentkit/internal/run"
)

// ErrPython leaves a hand-in to Python ak: text Go cannot read as Python does, a failure Python
// reports in its runtime's own words, and a fixer's done that runs earlier findings' proofs
// again under the worker's time limits, which come in a later milestone.
var ErrPython = errors.New("left to Python")

// outputCap is the most of a proof's output a row keeps: past it, its first and last halves.
const outputCap = 8 * 1024

// A turn is the record file's first row and the rows handed in since.
type turn struct {
	workspace any // the checkout, a path only as a string
	role      string
	findings  any // the blocking findings handed to the turn (handed)
	records   []*run.Object
}

// Hand checks what args hand in against the turn's record file and appends its row.
func Hand(args []string) error {
	path := os.Getenv("AK_HAND_IN")
	if path == "" || !regular(path) {
		return errors.New("hand-in needs an active worker turn; use it from the worker's shell")
	}
	file, err := lock.Edit(path)
	if err != nil {
		return ErrPython
	}
	defer file.Close()
	data, err := io.ReadAll(file)
	if err != nil || !utf8.Valid(data) {
		return ErrPython
	}
	t, err := read(data)
	if err != nil {
		return err
	}
	for _, arg := range args {
		if !utf8.ValidString(arg) {
			return ErrPython
		}
	}
	row, err := t.checked(args)
	if err == nil && row.Str("kind") == "done" && strings.HasPrefix(t.role, "fixer") {
		err = t.rerun()
	}
	if err != nil {
		return err
	}
	if _, err := file.WriteString(run.Line(row) + "\n"); err != nil {
		return ErrPython
	}
	return nil
}

// read is the turn as Python's main reads its record: every line's JSON, the lines split as a
// Python text file splits them, before the first row is judged the turn's and none a closing.
func read(data []byte) (*turn, error) {
	var rows []any
	for _, line := range strings.SplitAfter(newlines(string(data)), "\n") {
		if line == "" {
			continue // past the last line break
		}
		row, err := run.DecodeLimited([]byte(line))
		if errors.Is(err, run.ErrLoneSurrogate) || errors.Is(err, run.ErrLimit) {
			return nil, ErrPython
		} else if err != nil {
			return nil, fmt.Errorf("cannot hand in this record: %w", err)
		}
		rows = append(rows, row)
	}
	invalid := errors.New("the worker turn's record file is invalid; ask the loop to retry")
	if len(rows) == 0 {
		return nil, invalid
	}
	first, ok := rows[0].(*run.Object)
	if !ok {
		return nil, ErrPython // a row that is no object, in Python's own words
	} else if first.Str("kind") != "turn" {
		return nil, invalid
	}
	t := &turn{workspace: first.Get("workspace"), role: "reviewer", findings: []any{}}
	for _, row := range rows {
		record, ok := row.(*run.Object)
		if !ok {
			return nil, ErrPython
		} else if slices.Contains([]string{"done", "blocked", "not-needed"}, record.Str("kind")) {
			return nil, errors.New("this turn is already closed; hand in records before done, blocked or not-needed")
		}
		t.records = append(t.records, record)
	}
	t.records = t.records[1:]
	if !first.Has("workspace") {
		return nil, errors.New("cannot hand in this record: 'workspace'")
	}
	if first.Has("role") {
		if t.role, ok = first.Get("role").(string); !ok {
			return nil, ErrPython
		}
	}
	if first.Has("findings") {
		t.findings = first.Get("findings")
	}
	return t, nil
}

// checked is the row args hand in, or why ak refuses it, as Python's hand_in.checked decides.
func (t *turn) checked(args []string) (*run.Object, error) {
	row := run.NewObject()
	if len(args) > 0 {
		switch args[0] {
		case "blocked", "not-needed":
			if strings.HasPrefix(t.role, "reviewer") {
				return nil, errors.New("blocked and not-needed are only for executor or fixer turns")
			}
			if len(args) != 2 || blank(args[1]) {
				return nil, errors.New(`use blocked or not-needed with one nonempty "why"`)
			}
			row.Set("kind", args[0])
			row.Set("why", strings.TrimFunc(args[1], config.Space))
			return row, nil
		case "finding", "follow-up":
			if !strings.HasPrefix(t.role, "reviewer") {
				return nil, errors.New("finding and follow-up are only for review turns")
			}
		case "dispute":
			if !strings.HasPrefix(t.role, "fixer") {
				return nil, errors.New("dispute is only for fixer turns")
			}
		}
	}
	if len(args) == 1 && args[0] == "done" {
		row.Set("kind", "done")
		return row, nil
	}
	start := 4
	var what, why string
	var disputed *run.Object
	if len(args) > 0 && args[0] == "dispute" {
		if len(args) < 3 || blank(args[2]) {
			return nil, errors.New(`use dispute with path:line, "why it is wrong" and evidence`)
		}
		handed, err := t.handed()
		if err != nil {
			return nil, err
		}
		if disputed = named(handed, args[1]); disputed == nil {
			allowed := []string{}
			for _, item := range handed {
				allowed = append(allowed, site(item))
			}
			if len(allowed) == 0 {
				allowed = []string{"none"}
			}
			return nil, errors.New("dispute must name a blocking finding handed to this turn; you may dispute: " + strings.Join(allowed, ", "))
		}
		start, what, why = 3, disputed.Str("what"), args[2]
	} else {
		if len(args) < 4 || !slices.Contains([]string{"finding", "follow-up"}, args[0]) {
			return nil, errors.New("use finding or follow-up with path:line, what, why it matters and evidence, dispute, or done alone")
		}
		what, why = args[2], args[3]
	}
	if blank(what) || blank(why) {
		return nil, errors.New("supply both what is wrong and why it matters")
	}
	flags := map[string]string{}
	for i := start; i < len(args); i += 2 {
		_, duplicate := flags[args[i]]
		if !slices.Contains([]string{"--run", "--quote", "--before"}, args[i]) || duplicate || i+1 == len(args) {
			return nil, errors.New("use one evidence flag, --run COMMAND or --quote LINES, and --before PROOF for a follow-up that predates the task")
		}
		flags[args[i]] = args[i+1]
	}
	command, proven := flags["--run"]
	quote, hasQuote := flags["--quote"]
	if proven == hasQuote || blank(command+quote) {
		return nil, errors.New("supply evidence with exactly one of --run COMMAND or --quote LINES")
	}
	before, hasBefore := flags["--before"]
	if args[0] == "follow-up" {
		if hasBefore && blank(before) {
			return nil, errors.New("--before names the base or an ancestor commit, or verbatim lines from the named file at base")
		}
		if !hasBefore && !proven {
			return nil, errors.New("a follow-up without --before needs --run: its command becomes the check that fixes it")
		}
	} else if hasBefore {
		return nil, errors.New("use follow-up for a defect that existed before the task")
	}
	root, ok := t.workspace.(string)
	if !ok || strings.ContainsRune(root, 0) {
		return nil, ErrPython // what Python's Path refuses in its own words
	}
	if root = config.Resolve(root); !filepath.IsAbs(root) {
		return nil, ErrPython // no current directory, which Python's getcwd reports in its own words
	}
	path, line, err := checkedSite(args[1], root, quote, hasQuote)
	if err != nil && !errors.Is(err, ErrPython) {
		// A handed finding can name a file or line that a fix deleted. Only a
		// command can prove it again; a quote still has to exist in the checkout.
		handed, failed := t.handed()
		listed := named(handed, args[1])
		if failed != nil {
			return nil, failed
		} else if listed == nil || hasQuote {
			return nil, err
		}
		path, err = listed.Str("path"), nil
		line, _ = listed.Int("line")
		if filepath.IsAbs(path) || filepath.Clean(path) != path {
			return nil, ErrPython // a path Python's pathlib writes another way
		}
	}
	if err != nil {
		return nil, err
	}
	if args[0] == "follow-up" && command != "" && !planCheck(command, root) {
		return nil, errors.New("write a follow-up's --run as one shell command, without backticks, line breaks or this checkout's path: it becomes a plan check")
	}
	evidence := run.NewObject()
	if hasQuote {
		evidence.Set("quote", quote)
	} else {
		code, output, err := proof(command, root)
		switch {
		case err != nil:
			return nil, err
		case args[0] == "finding" && code == 0:
			return nil, errors.New("the command exited 0; write it to fail while the defect exists, or use --quote")
		case args[0] == "follow-up" && !hasBefore && code == 0:
			return nil, errors.New("the command exited 0; write it to fail while the defect exists")
		case args[0] == "dispute" && code != 0:
			return nil, errors.New("a dispute's command must exit 0 to show the behaviour is right")
		}
		evidence.Set("run", command)
		evidence.Set("returncode", code)
		evidence.Set("output", output)
	}
	row.Set("kind", args[0])
	row.Set("path", path)
	row.Set("line", line)
	row.Set("what", what)
	row.Set("why", why)
	row.Set("evidence", evidence)
	if args[0] == "follow-up" && hasBefore {
		row.Set("before", before)
	}
	if disputed != nil {
		row.Set("finding", disputed)
	}
	return row, nil
}

// handed is the blocking findings handed to the turn, read only as the loop writes them: each
// at a site (sited) and with a string what.
func (t *turn) handed() ([]*run.Object, error) {
	list, ok := t.findings.([]any)
	if !ok {
		return nil, ErrPython
	}
	handed := make([]*run.Object, len(list))
	for i, item := range list {
		finding, _ := item.(*run.Object)
		if finding == nil || !sited(finding) {
			return nil, ErrPython
		} else if _, ok := finding.Get("what").(string); !ok {
			return nil, ErrPython
		}
		handed[i] = finding
	}
	return handed, nil
}

// sited is whether a finding or dispute names its site as hand-in writes one: a string path and
// an integer line.
func sited(row *run.Object) bool {
	_, path := row.Get("path").(string)
	_, line := row.Int("line")
	return path && line
}

// site is a sited row's path:line.
func site(row *run.Object) string {
	line, _ := row.Int("line")
	return row.Str("path") + ":" + strconv.Itoa(line)
}

// named is the handed finding at the site, if one is.
func named(handed []*run.Object, at string) *run.Object {
	for _, finding := range handed {
		if site(finding) == at {
			return finding
		}
	}
	return nil
}

// rerun leaves to Python a fixer's done that would run an earlier finding's proof again: one
// handed in with a command, at a site no dispute of this turn names.
func (t *turn) rerun() error {
	disputed := map[string]bool{}
	for _, record := range t.records {
		if kind := record.Str("kind"); !record.Has("kind") || kind == "dispute" && !sited(record) {
			return ErrPython
		} else if kind == "dispute" {
			disputed[site(record)] = true
		}
	}
	handed, err := t.handed()
	if err != nil {
		return err
	}
	for _, finding := range handed {
		if evidence := finding.Dict("evidence"); evidence == nil || evidence.Truthy("run") && !disputed[site(finding)] {
			return ErrPython
		}
	}
	return nil
}

// checkedSite is the site's path relative to root and its line, once it names a line of a file
// inside root that holds the quote.
func checkedSite(site, root, quote string, hasQuote bool) (string, int, error) {
	colon := strings.LastIndexByte(site, ':')
	digits := site[colon+1:]
	if colon >= 1 && digits != "" && !config.Digits(digits) && strings.TrimFunc(digits, unicode.IsDigit) == "" {
		return "", 0, ErrPython // decimal digits past ASCII, which Python reads as a line
	}
	if colon < 1 || !config.Digits(digits) {
		return "", 0, fmt.Errorf("name the location as path:line with a numeric line")
	}
	name := site[:colon]
	if !filepath.IsAbs(name) {
		name = root + string(filepath.Separator) + name // its `..` left for Resolve to take after links
	}
	path := config.Resolve(name)
	relative, err := filepath.Rel(root, path)
	if err != nil || relative == ".." || strings.HasPrefix(relative, ".."+string(filepath.Separator)) || !regular(path) {
		return "", 0, fmt.Errorf("name a file that exists inside this checkout")
	}
	content, err := readText(path)
	if err != nil || len(digits) > 640 {
		// what Python may refuse in its runtime's own words: past 640 digits, int() does as
		// PYTHONINTMAXSTRDIGITS says
		return "", 0, ErrPython
	}
	lines := len(config.SplitLines(content))
	line, err := strconv.Atoi(digits)
	if err != nil || line < 1 || line > lines {
		return "", 0, fmt.Errorf("choose a line from 1 to %d in %s", lines, relative)
	}
	if hasQuote && (blank(quote) || !strings.Contains(content, quote)) {
		return "", 0, fmt.Errorf("use a quote found verbatim in the named file")
	}
	return relative, line, nil
}

// planCheck is whether a follow-up's command can check its plan line, as Python's
// hand_in.plan_check decides: one shell command on one line, without backticks or root.
func planCheck(command, root string) bool {
	return len(config.SplitLines(strings.TrimFunc(command, config.Space))) == 1 && !strings.Contains(command, "`") && !strings.Contains(command, root)
}

// proof runs a hand-in's command as Python's checked does: bash -c in the checkout, without the
// turn's variables, its output and errors spooled together in the checkout.  Its exit status is
// Python's returncode, a signal's number negated where one ended it.
func proof(command, root string) (int, string, error) {
	spool, err := os.CreateTemp(root, "")
	if err != nil {
		return 0, "", ErrPython
	}
	name := spool.Name()
	os.Remove(name) // nameless while it runs, as Python's TemporaryFile; Windows removes it closed
	defer func() { spool.Close(); os.Remove(name) }()
	cmd := exec.Command("bash", "-c", command)
	cmd.Dir, cmd.Env, cmd.Stdin, cmd.Stdout, cmd.Stderr = root, []string{}, os.Stdin, spool, spool
	for _, pair := range os.Environ() {
		if key, _, _ := strings.Cut(pair, "="); !slices.Contains([]string{"AK_HAND_IN", "AK_HAND_IN_CONTINUE", "AK_HAND_IN_FINDINGS"}, key) {
			cmd.Env = append(cmd.Env, pair)
		}
	}
	var exited *exec.ExitError
	if err := cmd.Run(); err != nil && !errors.As(err, &exited) {
		return 0, "", ErrPython
	}
	code := cmd.ProcessState.ExitCode()
	if status, ok := cmd.ProcessState.Sys().(syscall.WaitStatus); ok && status.Signaled() {
		code = -int(status.Signal())
	}
	output, err := excerpt(spool)
	return code, output, err
}

// excerpt is a proof's output as Python's output_excerpt cuts it: past outputCap bytes, its
// first and last halves around a note to rerun it.
func excerpt(spool *os.File) (string, error) {
	size, err := spool.Seek(0, io.SeekCurrent)
	if err != nil {
		return "", ErrPython
	} else if size <= outputCap {
		return part(spool, 0, io.SeekStart, outputCap)
	}
	head, err := part(spool, 0, io.SeekStart, outputCap/2)
	if err != nil {
		return "", err
	}
	tail, err := part(spool, -outputCap/2, io.SeekEnd, outputCap/2)
	return head + "\n[output truncated; rerun the command for full evidence]\n" + tail, err
}

// part is at most limit bytes of the spool from the offset, decoded with their line endings as
// they are.
func part(spool *os.File, offset int64, whence int, limit int64) (string, error) {
	if _, err := spool.Seek(offset, whence); err != nil {
		return "", ErrPython
	}
	data, err := io.ReadAll(io.LimitReader(spool, limit))
	if err != nil {
		return "", ErrPython
	}
	return decoded(data), nil
}

// regular is whether path names a regular file, its links followed.
func regular(path string) bool {
	info, err := os.Stat(path)
	return err == nil && info.Mode().IsRegular()
}

// blank is whether text is empty once Python's strip() takes its whitespace off.
func blank(text string) bool {
	return strings.TrimFunc(text, config.Space) == ""
}

// newlines is text with its line breaks as Python's text files read them: \r\n and \r as \n.
func newlines(text string) string {
	return strings.ReplaceAll(strings.ReplaceAll(text, "\r\n", "\n"), "\r", "\n")
}

// Quotes use Python's text view: universal newlines over what decoded reads.
func readText(path string) (string, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	return newlines(decoded(data)), nil
}

// decoded is data as Python's "replace" decodes it: one replacement per decoding error,
// including an incomplete UTF-8 prefix as a single error.
func decoded(data []byte) string {
	var text strings.Builder
	for len(data) > 0 {
		r, size := utf8.DecodeRune(data)
		if r == utf8.RuneError && size == 1 {
			for size < len(data) && !utf8.FullRune(data[:size+1]) {
				size++
			}
		}
		text.WriteRune(r)
		data = data[size:]
	}
	return text.String()
}
