package contract

import (
	"os"
	"regexp"
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/host"
	"agentkit/internal/logins"
	"agentkit/internal/run"
)

// missingLogin is an adapter's `auth` refusal for a login that is not there, and the place it
// looked: a provider's key in a settings file, or OAuth credentials.
var missingLogin = regexp.MustCompile(`^\S+: no (OAuth credentials in |provider key in )?(.+?)(?: and no CLAUDE_CODE_OAUTH_TOKEN| and none saved)?; run `)

// unavailable is why that harness cannot be checked here on account, "" where it can, as Python's
// contract.unavailable: its program missing, or its adapter's `auth` saying no.  A missing
// program or login is no coverage; broken is a saved login that no longer works, which fails.
func unavailable(name, account string) (string, bool) {
	program := name
	if version, _ := config.Words(name, "update", "version"); len(version) > 0 {
		program = version[0]
	}
	if harness.Binary(program) == "" {
		return program + " is not installed", false
	}
	why := refuses(name, account)
	if why == "" {
		return "", false
	}
	missing := missingLogin.FindStringSubmatch(why)
	// a settings file naming no key is a login never saved, not one gone bad
	keyless := missing != nil && missing[1] == "provider key in " && namesNo(missing[2], "apiKey")
	token, _ := config.WorkerToken(name, config.Login{})
	return why, missing == nil || exists(missing[2]) && !keyless || token != "" && exists(token)
}

// refuses is the line that harness's adapter's `auth` says no to account with, "" for any other
// answer, as Python's worker.auth_ok asks about every provider the config runs on the harness:
// unmarked, as nobody's run.
func refuses(name, account string) string {
	adapter, err := config.Adapter(name)
	if err != nil {
		return ""
	}
	env, err := config.ChildEnv()
	if err != nil {
		return ""
	}
	env = slices.DeleteFunc(env, func(pair string) bool { return strings.HasPrefix(pair, host.Marker+"=") })
	if account != "" {
		env = append(env, config.AccountEnv(account))
	}
	env = append(env, "AGENTKIT_PROVIDER="+strings.Join(config.HarnessProviders(name), " "))
	if answered, yes, line := logins.Auth(adapter, env); answered && !yes {
		return line
	}
	return ""
}

// namesNo is whether the file at path is a JSON object none of whose objects, at any depth, has
// the key.
func namesNo(path, key string) bool {
	data, err := os.ReadFile(path)
	if err != nil {
		return false
	}
	decoded, err := run.Decode(data)
	if _, object := decoded.(*run.Object); err != nil || !object {
		return false
	}
	var names func(value any) bool
	names = func(value any) bool {
		switch value := value.(type) {
		case *run.Object:
			return value.Has(key) || slices.ContainsFunc(value.Keys(), func(each string) bool { return names(value.Get(each)) })
		case []any:
			return slices.ContainsFunc(value, names)
		}
		return false
	}
	return !names(decoded)
}

// exists is whether anything, a dangling link too, stands at path.
func exists(path string) bool {
	_, err := os.Lstat(path)
	return err == nil
}
