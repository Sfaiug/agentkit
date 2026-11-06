package install

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strings"
	"unicode/utf8"

	"agentkit/internal/config"
	"agentkit/internal/task"
)

// The phone reaches the server through one authorized_keys entry, its comment tagged phoneTag,
// whose forced command is the whole session that key can have: one seat and you are in it,
// several and you pick.
const phoneTag, forced = "phone-termius", `command="ak attach"`

// errNotAKey is a --phone-key install.sh refuses, exit 2, at the phone's own step.
var errNotAKey = errors.New("--phone-key does not look like an OpenSSH public key")

// keyType is how an OpenSSH public key's type begins, where an entry with no options starts;
// publicKey is install.sh's reading of a key given, its type and the first character of its key.
var (
	keyType   = regexp.MustCompile(`^(ssh|ecdsa|sk)-`)
	publicKey = regexp.MustCompile(`^(ssh|ecdsa|sk)-.* [A-Za-z0-9+/]`)
)

// phone is install.sh's steps (h) and (e): the key given, a public key or a file whose first
// line is one, is appended once as the phone's, and each phone entry then runs `ak attach`, no
// other key touched.  sshd refuses an authorized_keys anyone else can write, so a file holding
// the phone's is left mode 600.
func phone(given string, out, errOut io.Writer) error {
	keys := filepath.Join(config.UserHome(), ".ssh", "authorized_keys")
	if given != "" {
		if err := addPhone(keys, given, out); err != nil {
			return err
		}
	}
	if info, err := os.Stat(keys); err != nil || !info.Mode().IsRegular() {
		return nil
	}
	if err := repoint(keys, out); err != nil {
		fmt.Fprintf(errOut, "note: %v; %s left unchanged, point the phone key at `ak attach` yourself\n", err, keys)
	}
	return nil
}

// addPhone appends the phone's entry for the key given, where no entry holds that key yet.
func addPhone(keys, given string, out io.Writer) error {
	key := given
	if info, err := os.Stat(given); err == nil && info.Mode().IsRegular() {
		read, err := os.ReadFile(given)
		if err != nil {
			return err
		}
		key, _, _ = strings.Cut(string(read), "\n")
	}
	// the key's words as a shell splits them, "" past the last
	words := append(strings.FieldsFunc(key, func(r rune) bool { return r == ' ' || r == '\t' || r == '\n' }), "", "")
	if !publicKey.MatchString(words[0] + " " + words[1]) {
		return fmt.Errorf("%w: %.40s", errNotAKey, key)
	}
	if err := os.MkdirAll(filepath.Dir(keys), 0o700); err != nil {
		return err
	}
	if err := os.Chmod(filepath.Dir(keys), 0o700); err != nil {
		return err
	}
	held, err := os.ReadFile(keys)
	if err != nil && !errors.Is(err, fs.ErrNotExist) {
		return err
	}
	if slices.ContainsFunc(strings.Split(string(held), "\n"), func(line string) bool {
		_, rest, _ := entry(line)
		fields := strings.Fields(rest)
		return len(fields) > 1 && fields[1] == words[1]
	}) {
		fmt.Fprintf(out, "ssh: the phone key is already in %s\n", keys)
	} else {
		line := fmt.Sprintf("%s,no-agent-forwarding,no-port-forwarding %s %s %s\n", forced, words[0], words[1], phoneTag)
		if len(held) > 0 && !bytes.HasSuffix(held, []byte("\n")) {
			line = "\n" + line // else the last entry would take the phone's as its comment
		}
		file, err := os.OpenFile(keys, os.O_WRONLY|os.O_APPEND|os.O_CREATE, 0o600)
		if err != nil {
			return err
		}
		_, err = file.WriteString(line)
		if err := errors.Join(err, file.Close()); err != nil {
			return err
		}
		fmt.Fprintf(out, "ssh: appended the phone key to %s with the `ak attach` forced command\n", keys)
	}
	return os.Chmod(keys, 0o600)
}

// repoint gives every phone entry the forced command, backing the file up first where it
// changes.
func repoint(keys string, out io.Writer) error {
	data, err := os.ReadFile(keys)
	if err == nil && !utf8.Valid(data) {
		err = fmt.Errorf("%s is not UTF-8", keys)
	}
	if err != nil {
		return err
	}
	read := task.Text(data) // as Python's read_text reads it, every line ending a newline
	var written strings.Builder
	found := false
	for _, line := range strings.SplitAfter(read, "\n") {
		opts, rest, ok := entry(line)
		if words := strings.Fields(rest); len(words) > 2 && slices.Contains(words[2:], phoneTag) {
			found, line = true, attached(opts, rest)
		} else if !ok && slices.Contains(strings.Fields(line), phoneTag) {
			// an authorized_keys guessed at is a locked door
			found = true
			fmt.Fprintf(out, "note: the %s line in %s has an unterminated quote; left alone\n", phoneTag, keys)
		}
		written.WriteString(line)
	}
	switch {
	case !found:
		fmt.Fprintf(out, "ssh: no %s key in %s; nothing to point at `ak attach`\n", phoneTag, keys)
		return nil
	case written.String() == read:
		fmt.Fprintf(out, "ssh: the %s key already runs `ak attach`\n", phoneTag)
	default:
		backup, err := config.BackUp(keys)
		if err != nil {
			return err
		}
		// in whole, so sshd never reads half a file, and mode 600 before it is in place
		tmp := keys + ".ak-tmp"
		if err := errors.Join(os.WriteFile(tmp, []byte(written.String()), 0o600), os.Chmod(tmp, 0o600)); err != nil {
			return err
		}
		if err := os.Rename(tmp, keys); err != nil {
			return err
		}
		fmt.Fprintf(out, "ssh: the %s key now runs `ak attach` (%s backed up to %s)\n", phoneTag, keys, filepath.Base(backup))
	}
	return os.Chmod(keys, 0o600)
}

// entry is an authorized_keys line read as sshd reads it: its options, comma-separated before
// its key's type, where a quote holds commas, spaces and escaped quotes; and the rest from there,
// the key's type, the key and its comment.  A comment or blank line has neither, and false is a
// quote that never ends.
func entry(line string) (opts []string, rest string, ok bool) {
	line = strings.TrimLeftFunc(line, config.Space)
	if line == "" || line[0] == '#' {
		return nil, "", true
	}
	if keyType.MatchString(line) {
		return nil, line, true
	}
	start, quoted := 0, false
	for i := 0; i < len(line); i++ {
		switch c := line[i]; {
		case quoted && c == '\\':
			i++
		case c == '"':
			quoted = !quoted
		case !quoted && c == ',':
			opts, start = append(opts, line[start:i]), i+1
		case !quoted && (c == ' ' || c == '\t'):
			return append(opts, line[start:i]), line[i:], true
		}
	}
	return nil, "", !quoted
}

// attached is an entry with its forced command `ak attach`: its command option replaced, or that
// one put first.
func attached(opts []string, rest string) string {
	if opts == nil {
		rest = " " + rest // a key's type follows its options after a space
	}
	at := slices.IndexFunc(opts, func(opt string) bool { return strings.HasPrefix(strings.ToLower(opt), "command=") })
	if at < 0 {
		opts, at = slices.Insert(opts, 0, ""), 0
	}
	opts[at] = forced
	return strings.Join(opts, ",") + rest
}
