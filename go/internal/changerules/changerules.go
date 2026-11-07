// Package changerules is the scope and rules a change is held to, Python's change_rules: the
// loop's gate on a branch after a turn, and a builder's `ak hand-in done` on the tree the loop
// will commit of its workspace, before the turn can end.
package changerules

import (
	"fmt"
	"regexp"
	"slices"
	"strings"
	"unicode/utf8"

	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/task"
)

const (
	bodyWords   = 300 // AGENTS.md's body past this only shrinks
	readmeWords = 300 // nor does a README
)

var (
	// a black-box test of the program from outside, which a port to another language keeps
	answerKey = regexp.MustCompile(`^tests/test_key_[^/]*\.py$`)
	prose     = []string{".md", ".markdown", ".mdx", ".rst", ".adoc"}
	frontKeys = append([]string{"tests", "health", "cleanup", "users", "features", "suite_image", "content", "setup", "alive", "nightly"}, config.PolicyKeys()...)
)

// A change is the work from base to head, head "HEAD" for the branch git has out, else a
// workspace's tree, which starts at HEAD's fork from base: the run's base still supplies its rules.
type change struct {
	g          gitcall.Git
	base, head string
	refs       []string // what a diff of the change names
}

func on(g gitcall.Git, base, head string) (*change, error) {
	c := &change{g: g, base: base, head: head, refs: []string{base + "...HEAD"}}
	if head != "HEAD" {
		fork, err := g.Must("merge-base", base, "HEAD")
		if err != nil {
			return nil, err
		}
		c.refs = []string{fork, head}
	}
	return c, nil
}

func (c *change) diff(args ...string) []string {
	return append(append([]string{"diff"}, args...), c.refs...)
}

// names splits git's NUL-separated names, none empty.
func names(listed string) []string {
	return slices.DeleteFunc(strings.Split(listed, "\x00"), func(name string) bool { return name == "" })
}

// Scope is the failure for paths the change makes outside the task's `files:` pathspecs, "" for
// none, Python's files_scope.
func Scope(g gitcall.Git, base, head string, specs []string) (string, error) {
	if len(specs) == 0 {
		return "", nil
	}
	c, err := on(g, base, head)
	if err != nil {
		return "", err
	}
	diff := c.diff("--name-only", "--no-renames", "-z")
	changed, err := g.Raw(diff...)
	if err != nil {
		return "", fmt.Errorf("files: %w", err)
	}
	inside, err := g.Raw(append(diff, append([]string{"--"}, specs...)...)...)
	if err != nil {
		return "", fmt.Errorf("files: %w", err)
	}
	outside := slices.DeleteFunc(names(changed), func(each string) bool { return slices.Contains(names(inside), each) })
	slices.Sort(outside)
	if len(outside) == 0 {
		return "", nil
	}
	return shown("outside files: " + strings.Join(outside, ", ")), nil
}

// Check is Python's rules_check: the refusal of a change that grows prose past what it may hold,
// changes Python with no answer key, or changes AGENTS.md so workers would not get it as written;
// "" for none.  Its attribute reads see g's index.
func Check(g gitcall.Git, base, head string) (string, error) {
	c, err := on(g, base, head)
	if err != nil {
		return "", err
	}
	failure, err := c.proseGrown()
	if err != nil {
		return "", err
	}
	if failure == "" {
		failure, err = c.keylessPython()
		if err != nil {
			return "", err
		}
	}
	if failure != "" {
		return shown(failure), nil
	}
	return c.agentsCheck()
}

// shown is a refusal with each byte that is no UTF-8 as `\xNN`: a name git keeps whole can hold
// bytes no log or prompt takes.
func shown(text string) string {
	var out strings.Builder
	for len(text) > 0 {
		r, size := utf8.DecodeRuneInString(text)
		if r == utf8.RuneError && size == 1 {
			fmt.Fprintf(&out, `\x%02x`, text[0])
		} else {
			out.WriteString(text[:size])
		}
		text = text[size:]
	}
	return out.String()
}

func words(text string) int { return len(strings.FieldsFunc(text, config.Space)) }

// proseGrown is the refusal for the first prose file the change grows, measured against the base,
// whose `content:` counts: a change cannot widen its own exemption.
func (c *change) proseGrown() (string, error) {
	content := strings.FieldsFunc(gitcall.DeclaredAt(c.g.Repo, c.base, "content"), config.Space)
	changed, err := c.g.Raw(c.diff("--name-only", "--no-renames", "--diff-filter=AMT", "-z")...)
	if err != nil {
		return "", err
	}
	for _, path := range names(changed) {
		lower := strings.ToLower(path)
		shaped := false
		for _, suffix := range prose {
			shaped = shaped || strings.HasSuffix(lower, suffix)
		}
		for _, prefix := range content {
			shaped = shaped && !strings.HasPrefix(path, prefix)
		}
		if !shaped || path == "AGENTS.md" {
			continue
		}
		before, err := c.g.Try("cat-file", "-p", c.base+":"+path)
		if err != nil {
			return "", err
		}
		after, err := c.g.Try("cat-file", "-p", c.head+":"+path)
		if err != nil {
			return "", err
		}
		floor, past := 0, ""
		if path == "README.md" {
			floor, past = readmeWords, fmt.Sprintf("past %d words ", readmeWords)
		}
		if words(after) > max(floor, words(before)) {
			return fmt.Sprintf("%s grows from %d to %d words; prose outside the project's `content:` %sonly shrinks. Move what this adds into a test, a check or a comment at the code it is about; words that are the product itself need the base's `content:` to name them first.", path, words(before), words(after), past), nil
		}
	}
	return "", nil
}

// keylessPython is the refusal for a change to Python outside tests/ with no answer key, where
// the base holds one: a change deleting its own frees nothing.
func (c *change) keylessPython() (string, error) {
	held, err := c.g.Must("ls-tree", "-r", "-z", "--name-only", c.base, "--", "tests/")
	if err != nil {
		return "", err
	}
	if !slices.ContainsFunc(names(held), answerKey.MatchString) {
		return "", nil
	}
	said, err := c.g.Raw(c.diff("--name-status", "--find-renames", "-z")...)
	if err != nil {
		return "", err
	}
	fields := strings.Split(said, "\x00")
	var python []string
	for i := 0; i+1 < len(fields) && fields[i] != ""; i += 2 {
		status, old := fields[i], fields[i+1]
		name := old
		if status == "D" {
			continue
		}
		if status[0] == 'R' {
			i++
			name = fields[i+1]
		}
		if answerKey.MatchString(name) {
			return "", nil
		}
		if strings.HasSuffix(name, ".py") && !strings.HasPrefix(name, "tests/") && (status != "R100" || !strings.HasSuffix(old, ".py")) {
			python = append(python, name)
		}
	}
	if len(python) == 0 {
		return "", nil
	}
	return fmt.Sprintf("Python changed with no answer key: %s. A change to a .py file outside tests/ adds, edits or moves in a tests/test_key_*.py in the same change: a black-box test of what it does.", strings.Join(python, ", ")), nil
}

// agentsCheck is the refusal of an AGENTS.md the change touches that workers would not get as
// written: a link, a Git filter, more than a harness reads of it, a body grown past what it may
// hold, or a front matter line ak does not read.
func (c *change) agentsCheck() (string, error) {
	g := c.g
	changed, err := g.Must(append(c.diff("--name-only", "--no-renames"), "--", "AGENTS.md")...)
	if err != nil || changed == "" {
		return "", err
	}
	entry, err := g.Must("ls-tree", c.head, "--", "AGENTS.md")
	if err != nil || entry == "" {
		return "", err // the change deleted it
	}
	if strings.HasPrefix(entry, "120000 ") {
		return "AGENTS.md is a link, which ak does not follow, so workers would get no rules from it: make AGENTS.md the file itself.", nil
	}
	filter, err := g.Must("check-attr", "filter", "--", "AGENTS.md")
	if err != nil {
		return "", err
	}
	if !strings.HasSuffix(filter, "unspecified") && !strings.HasSuffix(filter, "unset") {
		return "AGENTS.md must not go through a Git filter: ak reads its front matter as committed.", nil
	}
	limit, whose := config.ReadLimit()
	code, held, said, err := g.Bytes("cat-file", "--filters", c.head+":AGENTS.md")
	if err != nil {
		return "", err
	}
	if code != 0 {
		unknown := "ak cannot check it"
		if limit > 0 {
			unknown = fmt.Sprintf("its size against the %d bytes %s reads of it is unknown", limit, whose)
		}
		return fmt.Sprintf("AGENTS.md could not be read as a checkout holds it, so %s: %s", unknown, gitcall.Strip(gitcall.Decoded(string(said)))), nil
	}
	if limit > 0 && len(held) > limit {
		return fmt.Sprintf("AGENTS.md is %d bytes, past the %d bytes %s reads of it: tighten it.", len(held), limit, whose), nil
	}
	now, before := words(gitcall.AgentsBody(g.Repo, c.head)), words(gitcall.AgentsBody(g.Repo, c.base))
	if now > max(bodyWords, before) {
		return fmt.Sprintf("AGENTS.md's body grows from %d to %d words; past %d it only shrinks. Move what this adds into a test, a check or a comment at the code it is about.", before, now, bodyWords), nil
	}
	text := gitcall.Strip(task.Text([]byte(gitcall.Decoded(string(held)))))
	var unread []string
	for _, line := range task.FrontLines(text) {
		name, _, _ := strings.Cut(line, ":")
		if !slices.Contains(frontKeys, gitcall.Strip(name)) {
			unread = append(unread, "`"+gitcall.Strip(line)+"`")
		}
	}
	if len(unread) == 0 {
		return "", nil
	}
	return fmt.Sprintf("AGENTS.md front matter has lines ak does not read: %s (it reads %s): remove them, or fix the misspelled name.", strings.Join(unread, ", "), strings.Join(frontKeys, ", ")), nil
}
