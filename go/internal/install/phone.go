package install

import (
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"unicode/utf8"

	"agentkit/internal/config"
	"agentkit/internal/task"
)

// The phone reaches the server through one authorized_keys line, tagged phoneTag, whose forced
// command is the whole session that key can have: one seat and you are in it, several and you
// pick.
const phoneTag, forced = "phone-termius", `command="ak attach"`

// errNotAKey is a --phone-key install.sh refuses, exit 2, at the phone's own step.
var errNotAKey = errors.New("--phone-key does not look like an OpenSSH public key")

// keyType is how an OpenSSH public key's type begins, where a key line's options end; publicKey
// is install.sh's reading of a key, its type and the first character of its key.
var (
	keyType   = regexp.MustCompile(`^(ssh|ecdsa|sk)-`)
	publicKey = regexp.MustCompile(`^(ssh|ecdsa|sk)-.* [A-Za-z0-9+/]`)
)

// phone is install.sh's steps (h) and (e): the key given, a public key or a file whose first
// line is one, is appended once as the phone's, and each phone line then runs `ak attach`, no
// other key touched.  sshd refuses an authorized_keys anyone else can write, so what is written
// is mode 600.
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

// addPhone appends the phone's line for the key given, where that key is in no line yet.
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
	if strings.Contains(string(held), " "+words[1]) {
		fmt.Fprintf(out, "ssh: the phone key is already in %s\n", keys)
	} else {
		file, err := os.OpenFile(keys, os.O_WRONLY|os.O_APPEND|os.O_CREATE, 0o600)
		if err != nil {
			return err
		}
		_, err = fmt.Fprintf(file, "%s,no-agent-forwarding,no-port-forwarding %s %s %s\n", forced, words[0], words[1], phoneTag)
		if err := errors.Join(err, file.Close()); err != nil {
			return err
		}
		fmt.Fprintf(out, "ssh: appended the phone key to %s with the `ak attach` forced command\n", keys)
	}
	return os.Chmod(keys, 0o600)
}

// repoint gives every phone line the forced command, backing the file up first where it
// changes; a commented-out line stays as it is.
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
		if strings.Contains(line, phoneTag) && !strings.HasPrefix(strings.TrimLeftFunc(line, config.Space), "#") {
			found = true
			pointed, ok := attach(line)
			if !ok {
				fmt.Fprintf(out, "note: the %s line in %s has an unterminated command=; left alone\n", phoneTag, keys)
			}
			line = pointed
		}
		written.WriteString(line)
	}
	switch {
	case !found:
		fmt.Fprintf(out, "ssh: no %s key in %s; nothing to point at `ak attach`\n", phoneTag, keys)
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
	return nil
}

// attach is a key line with its forced command made `ak attach`, and false with the line as it
// is where its command never ends: an authorized_keys guessed at is a locked door.  sshd allows
// an escaped quote inside `command="..."`, so the command ends at the first quote not escaped.
func attach(line string) (string, bool) {
	start := strings.Index(line, `command="`)
	if start < 0 {
		// options are joined by commas, and whitespace ends them before the key type, so
		// leading indentation would end ours before the line's own
		line = strings.TrimLeftFunc(line, config.Space)
		if keyType.MatchString(line) {
			return forced + " " + line, true
		}
		return forced + "," + line, true
	}
	for i := start + len(`command="`); i < len(line); i++ {
		switch line[i] {
		case '\\':
			i++
		case '"':
			return line[:start] + forced + line[i+1:], true
		}
	}
	return line, false
}
