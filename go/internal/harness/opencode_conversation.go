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
// reported into its receipt while no other seat's record names it (opencode.py `conversation`),
// "" where neither names one yet: OpenCode's TUI is never told an id.
func opencodeConversation(record map[string]any) string {
	session, _ := opencodeFound(record, false)
	return session
}

// opencodeNamed is opencodeFound read strictly, naming none only where its launch's receipt holds
// no session file, or one naming a session another seat's record keeps.
func opencodeNamed(record map[string]any) (string, error) { return opencodeFound(record, true) }

// opencodeFound is opencodeConversation, and the error of a receipt that is there and cannot be
// read, or is not UTF-8, as Python's raises where it reads strictly (harness.unread): one that is
// gone names none, as does one there naming no session, unless read strictly.  The record comes
// first, as a follow whose receipt write failed keeps it alone.
func opencodeFound(record map[string]any, strictly bool) (string, error) {
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
	session := strings.TrimFunc(string(reported), config.Space)
	if !opencodeSession.MatchString(session) && strictly {
		return "", fmt.Errorf("%s names no OpenCode session", path)
	} else if !opencodeSession.MatchString(session) || namedElsewhere("opencode_launch", token, session) {
		return "", nil
	}
	return session, nil
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
	err = ending(argv, env)
	return err == nil, err
}

// ending runs a harness's command ending a conversation as Python's subprocess.run runs it with
// timeout=60 and check=True, nothing read from or kept of what it says: why it failed, said as
// Python says it.
func ending(argv, env []string) error {
	ctx, cancel := context.WithTimeout(context.Background(), time.Minute)
	defer cancel()
	command := exec.CommandContext(ctx, argv[0], argv[1:]...)
	if errors.Is(command.Err, exec.ErrDot) {
		command.Err = nil // Python's subprocess runs what a relative PATH entry finds
	}
	command.Env = env
	err := command.Run()
	if err == nil {
		return nil
	}
	quoted := make([]string, len(argv))
	for i, word := range argv {
		quoted[i] = commandhelp.Quote(word)
	}
	said := "Command '[" + strings.Join(quoted, ", ") + "]'"
	var exited *exec.ExitError
	switch {
	case ctx.Err() != nil:
		return errors.New(said + " timed out after 60 seconds")
	case errors.As(err, &exited):
		return fmt.Errorf("%s returned non-zero exit status %d.", said, exited.ExitCode())
	case errors.Is(err, exec.ErrNotFound):
		return &fs.PathError{Op: "exec", Path: argv[0], Err: syscall.ENOENT}
	}
	return err
}
