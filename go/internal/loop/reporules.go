package loop

import (
	"fmt"
	"regexp"
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

// raw is git's output with every byte kept: a name handed back to git names the same file.
func (r *repoPlace) raw(args ...string) (string, error) {
	code, out, said, err := r.git().Bytes(args...)
	if err != nil {
		return "", err
	}
	if code != 0 {
		return "", fmt.Errorf("git %s failed in %s: %s", strings.Join(args[:min(2, len(args))], " "), r.wt, gitcall.Strip(gitcall.Decoded(string(said))))
	}
	return string(out), nil
}

// rulesCheck is Python's rules_check: the refusal of a branch that grows prose past what it may
// hold, changes Python with no answer key, or changes AGENTS.md so workers would not get it as
// written; "" for none.
func (r *repoPlace) rulesCheck() (string, error) {
	failure, err := r.proseGrown()
	if err != nil {
		return "", err
	}
	if failure == "" {
		failure, err = r.keylessPython()
		if err != nil {
			return "", err
		}
	}
	if failure != "" {
		return shown(failure), nil
	}
	return r.agentsCheck()
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

// proseGrown is the refusal for the first prose file the branch grows, measured against the base,
// whose `content:` counts: a branch cannot widen its own exemption.
func (r *repoPlace) proseGrown() (string, error) {
	content := strings.FieldsFunc(gitcall.DeclaredAt(r.wt, r.baseSHA, "content"), config.Space)
	changed, err := r.raw("diff", "--name-only", "--no-renames", "--diff-filter=AMT", "-z", r.baseSHA+"...HEAD")
	if err != nil {
		return "", err
	}
	g := r.git()
	for _, path := range paths(changed) {
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
		before, err := g.Try("cat-file", "-p", r.baseSHA+":"+path)
		if err != nil {
			return "", err
		}
		after, err := g.Try("cat-file", "-p", "HEAD:"+path)
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

// keylessPython is the refusal for a branch changing Python outside tests/ with no answer key,
// where the base holds one: a branch deleting its own frees nothing.
func (r *repoPlace) keylessPython() (string, error) {
	held, err := r.git().Must("ls-tree", "-r", "-z", "--name-only", r.baseSHA, "--", "tests/")
	if err != nil {
		return "", err
	}
	keyed := false
	for _, name := range paths(held) {
		keyed = keyed || answerKey.MatchString(name)
	}
	if !keyed {
		return "", nil
	}
	said, err := r.raw("diff", "--name-status", "--find-renames", "-z", r.baseSHA+"...HEAD")
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

// agentsCheck is the refusal of an AGENTS.md the branch changed that workers would not get as
// written: a link, a Git filter, more than a harness reads of it, a body grown past what it may
// hold, or a front matter line ak does not read.
func (r *repoPlace) agentsCheck() (string, error) {
	g := r.git()
	changed, err := g.Must("diff", "--name-only", "--no-renames", r.baseSHA+"...HEAD", "--", "AGENTS.md")
	if err != nil || changed == "" {
		return "", err
	}
	entry, err := g.Must("ls-tree", "HEAD", "--", "AGENTS.md")
	if err != nil || entry == "" {
		return "", err // the branch deleted it
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
	code, held, said, err := g.Bytes("cat-file", "--filters", "HEAD:AGENTS.md")
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
	now, before := words(gitcall.AgentsBody(r.wt, "HEAD")), words(gitcall.AgentsBody(r.wt, r.baseSHA))
	if now > max(bodyWords, before) {
		return fmt.Sprintf("AGENTS.md's body grows from %d to %d words; past %d it only shrinks. Move what this adds into a test, a check or a comment at the code it is about.", before, now, bodyWords), nil
	}
	text := gitcall.Strip(task.Text([]byte(gitcall.Decoded(string(held)))))
	var unread []string
	for _, line := range task.FrontLines(text) {
		name, _, _ := strings.Cut(line, ":")
		known := false
		for _, key := range frontKeys {
			known = known || gitcall.Strip(name) == key
		}
		if !known {
			unread = append(unread, "`"+gitcall.Strip(line)+"`")
		}
	}
	if len(unread) == 0 {
		return "", nil
	}
	return fmt.Sprintf("AGENTS.md front matter has lines ak does not read: %s (it reads %s): remove them, or fix the misspelled name.", strings.Join(unread, ", "), strings.Join(frontKeys, ", ")), nil
}
