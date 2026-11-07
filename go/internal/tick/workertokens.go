package tick

import (
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"unicode/utf8"

	"agentkit/internal/config"
	"agentkit/internal/host"
	"agentkit/internal/notify"
	"agentkit/internal/run"
	"agentkit/internal/worker"
)

const tokenPollEvery = 86400 // the verb is asked at most once a day (watch.TOKEN_POLL_EVERY)

var tokenDays = regexp.MustCompile(`expires in (\d+) days`)

// pollTokens is the seat health row's first step (watch.poll_worker_token): each declared worker
// token's `auth` verb asked at most once a day, at once where its file's date is new or its end
// has passed since, and its answer kept per harness under `worker_tokens`; a verb that did not
// answer moves nothing.  A dead token is every seat's word, which Go does not word: errLeft, the
// state as it was.  A dry tick keeps no answer and reads none, so asks no verb.
func (t *ticking) pollTokens() error {
	tokens, err := config.WorkerTokens()
	if err != nil {
		return errLeft
	}
	now := epoch(t.clock())
	previous, kept := t.state.Dict("worker_tokens"), run.NewObject()
	for _, token := range tokens {
		harness, path := token[0], filepath.Join(config.Home(), "secrets", token[1])
		info, err := os.Stat(path)
		data, unread := os.ReadFile(path)
		// a file holding nothing, or what is no text, holds no token
		if err != nil || unread != nil || !utf8.Valid(data) || strings.TrimFunc(string(data), config.Space) == "" {
			continue
		}
		// st_mtime as Python's stat reckons it, so either program's record dates the same file
		mtime := float64(info.ModTime().Unix()) + float64(info.ModTime().Nanosecond())*1e-9
		record := run.NewObject()
		if previous != nil && previous.Dict(harness) != nil {
			record = previous.Dict(harness)
		}
		checked, dated := record.Num("checked_at")
		ends := mtime + config.TokenLife*86400
		if dated && 0 <= now-checked && now-checked < tokenPollEvery && run.Equal(record.Get("mtime"), run.Float(mtime)) &&
			!(checked < ends && ends <= now) {
			kept.Set(harness, record)
			continue
		}
		// a dry tick asks no verb: its record stands as it was
		answered, why := false, ""
		if !t.dry {
			answered, _, why = authOK(harness)
		}
		if !answered {
			if len(record.Keys()) > 0 {
				kept.Set(harness, record)
			}
			continue
		}
		var days any
		if found := tokenDays.FindStringSubmatch(why); found != nil {
			days = run.Number(found[1])
		}
		// `at` is when a dead token's episode began, which only Python's tick keeps
		kept.Set(harness, run.Fields("harness", harness, "remedy", token[2], "at", nil, "checked_at", now, "mtime", mtime,
			"days", days, "expired", strings.Contains(why, "worker token expired"), "why", why))
	}
	if slices.ContainsFunc(kept.Keys(), func(harness string) bool { return kept.Dict(harness).Truthy("expired") }) {
		return errLeft
	}
	if len(kept.Keys()) == 0 {
		t.state.Delete("worker_tokens")
	} else {
		t.state.Set("worker_tokens", kept)
	}
	return nil
}

// authOK is what the harness's adapter says of a turn's login, as worker.auth_ok asks about the
// harness as a whole: unmarked, as nobody's run, and for every provider the config runs on it;
// "seat" in args asks about the seat's interactive login instead.
func authOK(harness string, args ...string) (answered, yes bool, why string) {
	adapter, err := config.LoginAdapter(harness)
	env, unread := config.ChildEnv()
	if err != nil || unread != nil {
		return false, false, ""
	}
	env = slices.DeleteFunc(env, func(pair string) bool { return strings.HasPrefix(pair, host.Marker+"=") })
	return worker.Login(adapter, append(env, "AGENTKIT_PROVIDER="+strings.Join(config.HarnessProviders(harness), " ")), args...)
}

// remindTokens is the token reminder row (watch.remind_worker_tokens): the owner paged once a local
// day for each worker token that ends within remindWithin, as a login's end is, the card naming
// only its harness's token, the outbox keeping the token's warning.  The poll left none dead.
func (t *ticking) remindTokens() error {
	now := t.clock()
	tokens := t.state.Dict("worker_tokens")
	if tokens == nil {
		return nil
	}
	for _, harness := range tokens.Keys() {
		record := tokens.Dict(harness)
		reason := tokenWarning(record)
		if mtime, dated := record.Num("mtime"); reason == "" || !dated || mtime+config.TokenLife*86400-epoch(now) > remindWithin {
			continue
		}
		key := "token:" + harness + ":" + now.Format("2006-01-02")
		if err := notify.Remind(key, harness+" worker token", reason, t.log.line, t.log.errOut); err != nil {
			return err
		}
	}
	return nil
}

// tokenWarning is what every session reads while that worker token nears its end, "" where its
// record says none (watch.token_warning).
func tokenWarning(record *run.Object) string {
	harness, remedy := record.Str("harness"), record.Str("remedy")
	days, counted := record.Int("days")
	if harness == "" || remedy == "" || !counted || days < 0 || days > config.TokenWarn {
		return ""
	}
	return harness + " worker token expires in " + strconv.Itoa(days) + " days: " + remedy
}
