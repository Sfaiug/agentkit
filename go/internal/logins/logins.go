// Package logins is when each subscription's login ends and whose it is, as Python's logins module
// keeps them in state/logins.json, {provider: {account: {email, ends, plan, checked_at}}}: what each
// harness's adapter answers to `login-end`, read by every screen that warns before a login ends.
package logins

import (
	"cmp"
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/host"
	"agentkit/internal/lock"
	"agentkit/internal/run"
)

const (
	warnWithin = 7 * 86400        // seconds before its end a login turns its meter amber (logins.WARN_WITHIN)
	askTimeout = 20 * time.Second // the verb reads files on this machine; one that hangs answers nothing
)

func path() string { return filepath.Join(config.Home(), "state", "logins.json") }

// Of is what logins.json keeps for that login, "" being a provider's usual one; nil for nothing.
func Of(provider, account string) *run.Object {
	kept, _ := run.ReadJSON(path())
	if kept == nil || kept.Dict(provider) == nil {
		return nil
	}
	return kept.Dict(provider).Dict(cmp.Or(account, config.DefaultAccount))
}

// Ending is what is said of a login while it ends within warnWithin or has ended, `login
// owner@acme.test ends Mon 26 Oct 04:47 (in 2 days)` or `login ended Mon 26 Oct 04:47`, its meter
// amber meanwhile; "" for one further off or with no end written down (menu.login_notes).
func Ending(login *run.Object, now time.Time) string {
	if login == nil {
		return ""
	}
	ends, ok := login.Num("ends")
	if !ok || ends-float64(now.UnixNano())/1e9 > warnWithin {
		return ""
	}
	at := time.Unix(int64(ends), 0).Local()
	when := "ended " + at.Format("Mon 02 Jan 15:04")
	if ends > float64(now.UnixNano())/1e9 {
		day := func(t time.Time) time.Time { y, m, d := t.Date(); return time.Date(y, m, d, 0, 0, 0, 0, time.UTC) }
		soon := map[int]string{0: "today", 1: "tomorrow"}
		days := int(day(at).Sub(day(now.Local())).Hours() / 24)
		when = "ends " + at.Format("Mon 02 Jan 15:04") + " (" + cmp.Or(soon[days], fmt.Sprintf("in %d days", days)) + ")"
	}
	if email := login.Str("email"); email != "" {
		return "login " + email + " " + when
	}
	return "login " + when
}

// Renewed asks a login just made again in ak when it ends, through its harness's adapter's
// `login-end`, and keeps the answer with the rest, so its meter is grey as the screen comes back
// (logins.renewed); one that answers nothing changes nothing.  Asked and written under the lock
// Python's tick asks and writes under, one at a time.
func Renewed(provider, account, harness string) {
	account = cmp.Or(account, config.DefaultAccount)
	if config.EnsureDirs() != nil {
		return
	}
	held, err := lock.Wait(context.Background(), filepath.Join(config.Home(), "state", ".logins.lock"))
	if err != nil {
		return
	}
	defer held.Close()
	answer := Ask(harness, account)
	if answer == nil {
		return
	}
	kept, _ := run.ReadJSON(path())
	if kept == nil {
		kept = run.NewObject()
	}
	theirs := kept.Dict(provider)
	if theirs == nil {
		theirs = run.NewObject()
	}
	login := theirs.Dict(account)
	if login == nil {
		login = run.NewObject()
	}
	login = login.Copy()
	for _, key := range answer.Keys() {
		login.Set(key, answer.Get(key))
	}
	login.Set("checked_at", float64(time.Now().UnixNano())/1e9)
	theirs.Set(account, login)
	kept.Set(provider, theirs)
	tmp := filepath.Join(config.Home(), "state", "logins.tmp")
	if os.WriteFile(tmp, []byte(run.Encode(kept)+"\n"), 0o666) == nil {
		os.Rename(tmp, path())
	}
}

// Ask is the adapter's {email, ends, plan} for that account's login, or nil where it said nothing
// usable: no harness, no such verb, a failure, a timeout, or anything but that object
// (logins._ask).
func Ask(harness, account string) *run.Object {
	adapter, err := config.LoginAdapter(harness)
	if err != nil || harness == "" {
		return nil
	}
	ctx, cancel := context.WithTimeout(context.Background(), askTimeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, adapter, "login-end")
	cmd.Env, cmd.WaitDelay = append(os.Environ(), config.AccountEnv(account)), time.Second
	stop := host.AdapterCall(cmd) // hung, its readers die with it rather than pile up
	cmd.Cancel = func() error { stop(); return nil }
	out, err := cmd.Output()
	if err != nil {
		return nil
	}
	value, err := run.Decode(out)
	said, _ := value.(*run.Object)
	if err != nil || said == nil {
		return nil
	}
	answer := run.NewObject()
	for _, key := range []string{"email", "ends", "plan"} {
		word, isText := said.Get(key).(string)
		_, isNumber := said.Num(key)
		switch {
		case said.Get(key) == nil:
		case key == "ends" && !isNumber, key != "ends" && (!isText || word == ""):
			return nil
		}
		answer.Set(key, said.Get(key))
	}
	return answer
}
