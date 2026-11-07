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
	if facts.tick == nil {
		return nil, ErrUnread
	}
	answers := facts.tick.Dict("auth_out")
	if answers == nil && facts.tick.Truthy("auth_out") {
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
// only nearing its day is a line on the ak screen, never a word.  A dead token's word begins again
// where a replaced file is still dead (watch.token_episode_restarted).
func everySeatsNews(facts climbing) (*answer, error) {
	if facts.tick == nil {
		return nil, ErrUnread
	}
	if facts.tick.Truthy("gh_out") {
		gh := facts.tick.Dict("gh_out")
		if gh == nil {
			return nil, ErrUnread // Python's `.get` on it raises
		}
		return &answer{word: "needs you", reason: "GitHub is logged out: run `gh auth login -p https -w`", since: gh.Get("at")}, nil
	}
	tokens := facts.tick.Dict("worker_tokens")
	if tokens == nil {
		return nil, nil
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
			return nil, ErrUnread // Python words whatever value they hold
		}
		return &answer{word: "needs you", reason: harness + " worker token expired: " + remedy, since: record.Get("at"), anew: true}, nil
	}
	return nil, nil
}

// tickFound is watch.json as the last tick left it, the one reading of it a climb reads: empty
// where none stands, nil where it holds no object Go reads.
func tickFound(state string) *run.Object {
	saved, err := run.ReadJSON(filepath.Join(state, "watch.json"))
	if errors.Is(err, fs.ErrNotExist) {
		return run.NewObject()
	}
	if err != nil {
		return nil
	}
	return saved
}
