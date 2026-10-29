// Package harness is how a harness starts: from a model's adapter, the command line a seat
// runs.  It hides each adapter's command template and flags, which only the adapter's
// `interactive` verb spells, and what ak puts around that line: the seat's login, ak's editor,
// and the refusal of a harness that would take instructions beside the seat's rulebook.
package harness

import (
	"bytes"
	"crypto/rand"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// cannotPin is the adapter's answer when its TUI cannot be told a conversation id.
const cannotPin = 3

var errCannotPin = errors.New("cannot pin")

// Seat is the command line a new seat on the model `name` runs, on that account ("" or
// "default" for the usual login), and the conversation it opens under, "" where its harness
// cannot be told one.  told is what the adapter is told beyond this process's environment.
func Seat(name string, model config.Model, account string, told map[string]string) ([]string, string, error) {
	conversation := uuid()
	cmd, err := interactive(name, model, account, told, conversation, "new")
	if errors.Is(err, errCannotPin) {
		conversation = ""
		cmd, err = interactive(name, model, account, told)
	}
	return cmd, conversation, err
}

func interactive(name string, model config.Model, account string, told map[string]string, conversation ...string) ([]string, error) {
	adapter, err := config.Adapter(model.Harness)
	if err != nil {
		return nil, err
	}
	if account == "default" {
		account = ""
	}
	run := exec.Command(adapter, append([]string{"interactive", model.ID, model.Effort}, conversation...)...)
	// with no rulebook named, the adapter writes the seat's own, where told says; the last of
	// a name's values is the one it gets
	run.Env = append(os.Environ(), "AGENTKIT_ACCOUNT="+account, "AGENTKIT_FIRST_PROMPT=", "AGENTKIT_RULEBOOK=")
	for key, value := range told {
		run.Env = append(run.Env, key+"="+value)
	}
	var stderr bytes.Buffer
	run.Stderr = &stderr
	out, err := run.Output()
	code := run.ProcessState.ExitCode()
	if len(conversation) > 0 && code == cannotPin {
		return nil, errCannotPin
	}
	line := strings.TrimSpace(string(out))
	if err != nil || line == "" {
		return nil, fmt.Errorf("%s interactive exited %d without a command for %s: %s", filepath.Base(adapter), code, name, last(strings.TrimSpace(stderr.String()), 300))
	}
	words, err := split(line)
	if err != nil {
		return nil, fmt.Errorf("%s interactive printed a command that will not parse (%s): %s", filepath.Base(adapter), err, first(line, 200))
	}
	if len(words) == 0 {
		return nil, fmt.Errorf("%s interactive printed no command for %s", filepath.Base(adapter), name)
	}
	// ak's editor is the seat's own, so the owner's unsent text can be set aside for a line of
	// ak's (agentkit/aside_editor.py), the owner's beside it
	owner, set := os.LookupEnv("AK_OWNER_EDITOR")
	if !set {
		owner = os.Getenv("VISUAL")
		if owner == "" {
			owner = os.Getenv("EDITOR")
		}
	}
	editor := filepath.Join(config.Repo(), "tools", "aside-editor")
	cmd := append([]string{"env", "AGENTKIT_ACCOUNT=" + account, "VISUAL=" + editor, "EDITOR=" + editor, "AK_OWNER_EDITOR=" + owner}, words...)
	// a seat's only instructions are its rulebook: a file its harness reads on its own, and
	// cannot be told not to, is refused rather than read beside it
	found, err := config.Unswitched(model.Harness, environment(cmd))
	if err != nil {
		return nil, err
	}
	for _, path := range found {
		if _, err := os.Stat(path); err == nil {
			return nil, fmt.Errorf("%s's harness reads %s on its own and has no switch for it, so a seat on it would take instructions beside its rulebook: move it away, or open the seat on a model of another harness", name, path)
		}
	}
	return cmd, nil
}

// launcher is a record's `id_source` for a conversation id the launcher handed out.
const launcher = "launcher"

var launchToken = regexp.MustCompile(`^[0-9a-f]{32}$`)

// Rewrites is whether ak rewrites that seat record of the harness, or may, before anything
// reads the seat as resumable (each `reconcile` in agentkit/harness): a conversation nothing
// vouches for is dropped, and Codex's says it is resumable only where its launch receipt,
// which Go does not read, proves a thread.  A field rewritten to what it holds is no rewrite.
func Rewrites(harness string, record *run.Object) bool {
	vouched := []string{launcher}
	switch harness {
	case "codex":
		token := record.Str("codex_launch")
		if launchToken.MatchString(token) && exists(filepath.Join(config.Home(), "state", "codex-launch-"+token+".json")) {
			return true
		}
		resumable := record.Get("resumable")
		number, numeric := run.Num(resumable)
		return resumable != false && !(numeric && number == 0)
	case "claude":
		vouched = append(vouched, "claude-hook")
	}
	return record.Truthy("conversation") && !slices.Contains(vouched, record.Str("id_source"))
}

func exists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}

var assignment = regexp.MustCompile(`^[A-Za-z_][A-Za-z0-9_]*=`)

// environment is this process's environment as the command line's leading `env` words leave
// it: each NAME=value set, each `-u NAME` unset.
func environment(cmd []string) map[string]string {
	values := map[string]string{}
	for _, entry := range os.Environ() {
		key, value, _ := strings.Cut(entry, "=")
		values[key] = value
	}
	for len(cmd) > 0 && cmd[0] == "env" {
		for cmd = cmd[1:]; len(cmd) > 0; {
			if cmd[0] == "-u" && len(cmd) > 1 {
				delete(values, cmd[1])
				cmd = cmd[2:]
			} else if assignment.MatchString(cmd[0]) {
				key, value, _ := strings.Cut(cmd[0], "=")
				values[key], cmd = value, cmd[1:]
			} else if strings.HasPrefix(cmd[0], "-") {
				cmd = cmd[1:]
			} else {
				break
			}
		}
	}
	return values
}

// split is a command line's words, as a POSIX shell, and Python's shlex.split, read them.
func split(line string) ([]string, error) {
	var words []string
	var word strings.Builder
	quote, inWord, escaped := rune(0), false, false
	for _, r := range line {
		switch {
		case escaped:
			if quote == '"' && r != '"' && r != '\\' {
				word.WriteRune('\\')
			}
			word.WriteRune(r)
			escaped = false
		case r == '\\' && quote != '\'':
			escaped, inWord = true, true
		case quote != 0 && r == quote:
			quote = 0
		case quote != 0:
			word.WriteRune(r)
		case r == '\'' || r == '"':
			quote, inWord = r, true
		case r == ' ' || r == '\t' || r == '\n' || r == '\r':
			if inWord {
				words, inWord = append(words, word.String()), false
				word.Reset()
			}
		default:
			word.WriteRune(r)
			inWord = true
		}
	}
	if escaped {
		return nil, errors.New("No escaped character")
	}
	if quote != 0 {
		return nil, errors.New("No closing quotation")
	}
	if inWord {
		words = append(words, word.String())
	}
	return words, nil
}

var plain = regexp.MustCompile(`^[\w@%+=:,./-]+$`)

// Join is a command line a shell reads back as these words, as Python's shlex.join writes it.
func Join(cmd []string) string {
	quoted := make([]string, len(cmd))
	for i, word := range cmd {
		quoted[i] = word
		if !plain.MatchString(word) {
			quoted[i] = "'" + strings.ReplaceAll(word, "'", `'"'"'`) + "'"
		}
	}
	return strings.Join(quoted, " ")
}

func uuid() string {
	b := make([]byte, 16)
	rand.Read(b)
	b[6], b[8] = b[6]&0x0f|0x40, b[8]&0x3f|0x80
	return fmt.Sprintf("%x-%x-%x-%x-%x", b[:4], b[4:6], b[6:8], b[8:10], b[10:])
}

func first(text string, n int) string {
	if runes := []rune(text); len(runes) > n {
		return string(runes[:n])
	}
	return text
}

func last(text string, n int) string {
	if runes := []rune(text); len(runes) > n {
		return string(runes[len(runes)-n:])
	}
	return text
}
