package harness

import (
	"encoding/base64"
	"errors"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// codexLogin is the Codex home of the login a call is on, as adapters/codex.sh picks it: an
// account's own where $AGENTKIT_ACCOUNT names one, which nothing of the usual login answers for;
// else $CODEX_HOME, unless that is an account's a seat on it handed down; else ~/.codex.
func codexLogin() string {
	home := config.UserHome()
	if account := os.Getenv("AGENTKIT_ACCOUNT"); account != "" {
		return home + "/.codex-" + account
	}
	if set := os.Getenv("CODEX_HOME"); set != "" && !strings.HasPrefix(set, home+"/.codex-") {
		return set
	}
	return filepath.Join(home, ".codex")
}

// codexAccountHome makes an account's Codex home, as adapters/codex.sh `home` does: it shares
// the usual one's conversations and config.toml, so a thread begun on one subscription resumes
// on the other, and keeps only its auth.json of its own.
func codexAccountHome(home string) error {
	usual := filepath.Join(config.UserHome(), ".codex")
	if err := os.MkdirAll(home, 0o777); err != nil {
		return err
	}
	for _, store := range []string{"sessions", "archived_sessions"} {
		if err := os.MkdirAll(filepath.Join(usual, store), 0o777); err != nil {
			return err
		}
		if _, err := os.Stat(filepath.Join(home, store)); errors.Is(err, os.ErrNotExist) {
			if err := os.Symlink(filepath.Join(usual, store), filepath.Join(home, store)); err != nil {
				return err
			}
		}
	}
	settings := filepath.Join(usual, "config.toml")
	if info, err := os.Stat(settings); err == nil && info.Mode().IsRegular() {
		if _, err := os.Stat(filepath.Join(home, "config.toml")); errors.Is(err, os.ErrNotExist) {
			return os.Symlink(settings, filepath.Join(home, "config.toml"))
		}
	}
	return nil
}

// codexAuth is adapters/codex.sh `auth`: whether a turn can sign in on the login's auth.json, its
// access token there and the expiry it records, where it records one.  `seat` asks the same: a
// seat and a turn on Codex sign in on the one login.
func codexAuth(config.Login, bool) Answer {
	path := filepath.Join(codexLogin(), "auth.json")
	no := func(why string) Answer { return Answer{Line: "codex: " + why + "; run `codex login`"} }
	data, _ := os.ReadFile(path)
	if blank(string(data)) {
		return no("no " + path)
	}
	value, _ := run.Decode(data)
	auth, _ := value.(*run.Object)
	if auth == nil {
		return no(path + " carries no access token")
	}
	// jq's `.tokens.<key> // .<key>`: the login's tokens' own, else the file's, null and false
	// standing for none
	either := func(key string) any {
		for _, held := range []*run.Object{auth.Dict("tokens"), auth} {
			if held == nil {
				continue
			}
			if value := held.Get(key); value != nil && value != false {
				return value
			}
		}
		return nil
	}
	if token, _ := either("access_token").(string); token == "" {
		return no(path + " carries no access token")
	}
	// its expiry as jq's tostring spells it, anything but a number or a string being no digits
	ends := "?"
	switch at := either("expires_at").(type) {
	case nil:
		ends = ""
	case string:
		ends = at
	case run.Number:
		ends = string(at)
	}
	if ends == "" {
		return Answer{Yes: true, Line: "codex: " + path + " is present and records no expiry" + codexWho(auth)}
	}
	seconds, err := strconv.ParseInt(ends, 10, 64)
	if err != nil || strings.TrimLeft(ends, "0123456789") != "" {
		return no("the expiry in " + path + " cannot be read")
	}
	if len(ends) > 11 { // milliseconds where it records them
		seconds /= 1000
	}
	if seconds <= time.Now().Unix() {
		return no("the token in " + path + " expired")
	}
	return Answer{Yes: true, Line: "codex: the token in " + path + " is still valid" + codexWho(auth)}
}

// codexWho is whose the login is, the email its id token names, as `; logged in as <email>`;
// "" where it names nobody.
func codexWho(auth *run.Object) string {
	tokens := auth.Dict("tokens")
	if tokens == nil {
		return ""
	}
	parts := strings.Split(tokens.Str("id_token"), ".")
	if len(parts) < 2 {
		return ""
	}
	data, err := base64.RawURLEncoding.DecodeString(strings.TrimRight(parts[1], "="))
	value, _ := run.Decode(data)
	claims, _ := value.(*run.Object)
	if err != nil || claims == nil || claims.Str("email") == "" {
		return ""
	}
	return "; logged in as " + claims.Str("email")
}

// codexAccountFlags are what a seat on an account adds to its Codex's line, as codex-seat.py
// does: its named home signs in on its own file, never the usual login's Keychain entry, and
// trusts the seat's folder in this launch's own config too.
func codexAccountFlags(env []string) []string {
	if account, _ := codexEnv(env, "AGENTKIT_ACCOUNT"); account == "" {
		return nil
	}
	here, _ := os.Getwd()
	return []string{"-c", `cli_auth_credentials_store="file"`, "-c", "projects." + codexJSON(codexResolved(here)) + `.trust_level="trusted"`}
}
