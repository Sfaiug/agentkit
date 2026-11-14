package harness

import (
	"cmp"
	"context"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"syscall"
	"time"
	"unicode/utf8"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
)

var opencodeSession = regexp.MustCompile(`^ses_[0-9A-Za-z]+$`)

// opencodeConversation is the session that seat's record followed to, else the one its launch
// reported into its receipt (opencode.py `conversation`), "" where neither names one yet:
// OpenCode's TUI is never told an id.
func opencodeConversation(record map[string]any) string {
	session, _ := opencodeFound(record)
	return session
}

// opencodeFound is opencodeConversation, and the error of a receipt that is there and cannot be
// read, or is not UTF-8, as Python's raises where it reads strictly (harness.unread): one that is
// gone names none.  The record comes first, as a follow whose receipt write failed keeps it alone.
func opencodeFound(record map[string]any) (string, error) {
	if session, _ := record["conversation"].(string); opencodeSession.MatchString(session) {
		return session, nil
	}
	token, _ := record["opencode_launch"].(string)
	if !launchToken.MatchString(token) {
		return "", nil
	}
	path := filepath.Join(opencodeReceipt(token), "session")
	reported, err := os.ReadFile(path)
	if errors.Is(err, fs.ErrNotExist) {
		return "", nil
	} else if err != nil {
		return "", err
	} else if !utf8.Valid(reported) {
		return "", fmt.Errorf("%s is not UTF-8", path)
	}
	if session := strings.TrimFunc(string(reported), config.Space); opencodeSession.MatchString(session) {
		return session, nil
	}
	return "", nil
}

// opencodeEnd is `opencode session delete`, which takes the session with its children and
// messages, run only where ends(opencode.db) holds right before it starts (opencode.py
// `end_conversation`): whether it went.  `--standalone` runs it on a private server over the
// database opencodeIdle read, never on the background service on its one port, which may serve
// another.
func opencodeEnd(session string, ends func(database string) bool) (bool, error) {
	if !opencodeSession.MatchString(session) || !ends(opencodeDatabase()) {
		return false, nil
	}
	argv := []string{cmp.Or(Binary("opencode"), "opencode"), "session", "delete", "--standalone", session}
	env, err := config.ChildEnv()
	if err != nil {
		return false, err
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Minute)
	defer cancel()
	command := exec.CommandContext(ctx, argv[0], argv[1:]...)
	command.Env = env
	if err := command.Run(); err != nil {
		return false, called(argv, err, ctx.Err() != nil)
	}
	return true, nil
}

// called is why that command, run with a minute to finish, failed, as Python's subprocess.run
// says it with check=True.
func called(argv []string, err error, late bool) error {
	quoted := make([]string, len(argv))
	for i, word := range argv {
		quoted[i] = commandhelp.Quote(word)
	}
	command := "Command '[" + strings.Join(quoted, ", ") + "]'"
	var exited *exec.ExitError
	switch {
	case late:
		return errors.New(command + " timed out after 60 seconds")
	case errors.As(err, &exited):
		return fmt.Errorf("%s returned non-zero exit status %d.", command, exited.ExitCode())
	case errors.Is(err, exec.ErrNotFound):
		return &fs.PathError{Op: "exec", Path: argv[0], Err: syscall.ENOENT}
	}
	return err
}
