package seat

import (
	"cmp"
	"errors"
	"io/fs"
	"path/filepath"
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// tickLogins are what the tick leaves in watch.json of the logins a seat cannot move without:
// what each harness's `auth` verb answered, gh found logged out, and the daily ask of each worker
// token.  The ladder's first rungs read them, and nothing else of a word does.
var tickLogins = []string{"auth_out", "gh_out", "worker_tokens"}

// loginOut: [1] the tick found the seat's own login refused, asking its harness's `auth` verb
// (watch.logged_out); anything but a recorded no blocks nothing, and a seat nobody is in, or one no
// record names a harness for, has no login to ask about.
func loginOut(facts climbing) (*answer, error) {
	saved, err := tickFound(facts.state)
	if err != nil {
		return nil, err
	}
	answers := saved.Dict("auth_out")
	if answers == nil && saved.Truthy("auth_out") {
		return nil, ErrUnread // Python's `.get` on it raises
	}
	if facts.gone != nil || facts.own == "" || answers == nil {
		return nil, nil
	}
	found := answers.Dict(facts.own)
	if found == nil || found.Get("ok") != false {
		return nil, nil
	}
	auth, err := config.Section(facts.own, "auth")
	if err != nil {
		return nil, ErrUnread
	}
	remedy, _ := auth["remedy"].(string) // the harness's own, from its manifest (watch.login_reason)
	return &answer{word: "needs you", reason: facts.own + " login expired: open it and " + cmp.Or(remedy, "log in again"),
		since: found.Get("at")}, nil
}

// everySeatsNews: [1b] gh logged out, the one login no harness owns, and [1c] a dead worker token,
// each every seat's word on any harness, as any seat's next delivery or turn fails on it.  A token
// only nearing its day is a line on the ak screen, never a word.
func everySeatsNews(facts climbing) (*answer, error) {
	saved, err := tickFound(facts.state)
	if err != nil {
		return nil, err
	}
	if saved.Truthy("gh_out") {
		gh := saved.Dict("gh_out")
		if gh == nil {
			return nil, ErrUnread // Python's `.get` on it raises
		}
		return &answer{word: "needs you", reason: "GitHub is logged out: run `gh auth login -p https -w`", since: gh.Get("at")}, nil
	}
	reason, at, err := deadToken(saved)
	if reason == "" {
		return nil, err
	}
	return &answer{word: "needs you", reason: reason, since: at}, nil
}

// deadToken is the first dead worker token's reason, by harness, and since when the tick found it
// dead (watch.token_alert of watch.token_dead): none while every token lives.
func deadToken(saved *run.Object) (string, any, error) {
	tokens := saved.Dict("worker_tokens")
	if tokens == nil {
		return "", nil, nil
	}
	keys := tokens.Keys()
	slices.Sort(keys)
	for _, key := range keys {
		record := tokens.Dict(key)
		if record == nil || !record.Truthy("expired") || !record.Truthy("harness") || !record.Truthy("remedy") {
			continue
		}
		harness, named := record.Get("harness").(string)
		remedy, given := record.Get("remedy").(string)
		if !named || !given {
			return "", nil, ErrUnread // Python words whatever value they hold
		}
		return harness + " worker token expired: " + remedy, record.Get("at"), nil
	}
	return "", nil, nil
}

// restarted is when a dead token's episode began again, for a word standing on its reason since
// before then: a replaced file still dead is a new episode, never the old one continued
// (watch.token_episode_restarted).
func restarted(reason string, wordSince any) (any, bool) {
	saved, err := tickFound(filepath.Join(config.Home(), "state"))
	if err != nil {
		return nil, false
	}
	dead, at, _ := deadToken(saved)
	began, dated := run.Num(at)
	since, sinced := run.Num(wordSince)
	return at, dead != "" && dead == reason && dated && sinced && began > since
}

// tickFound is watch.json as the last tick left it, empty where none stands; ErrUnread where it holds
// no object Go reads.
func tickFound(state string) (*run.Object, error) {
	saved, err := run.ReadJSON(filepath.Join(state, "watch.json"))
	if errors.Is(err, fs.ErrNotExist) {
		return run.NewObject(), nil
	}
	if err != nil || saved == nil {
		return nil, ErrUnread
	}
	return saved, nil
}
