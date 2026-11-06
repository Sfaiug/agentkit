package notify

import (
	"context"
	"errors"
	"os"
	"path/filepath"

	"agentkit/internal/config"
	"agentkit/internal/lock"
	"agentkit/internal/logins"
	"agentkit/internal/run"
)

// RefreshLogins refreshes Python's logins.json under its record lock as at now and returns what it
// keeps (logins.refresh). A failed read keeps the last answer and only dates the ask.
func RefreshLogins(now float64) (*run.Object, error) {
	subs, err := config.Subscriptions()
	if err != nil {
		return nil, err
	}
	if err := config.EnsureDirs(); err != nil {
		return nil, err
	}
	held, err := lock.Wait(context.Background(), filepath.Join(state(), ".logins.lock"))
	if err != nil {
		return nil, err
	}
	defer held.Close()
	old, err := run.ReadJSON(filepath.Join(state(), "logins.json"))
	if errors.Is(err, run.ErrLoneSurrogate) {
		return nil, ErrUnread
	}
	if old == nil {
		old = run.NewObject()
	}
	kept := run.NewObject()
	for _, sub := range subs {
		accounts, err := config.Accounts(sub.Name)
		if err != nil {
			return nil, err
		}
		if len(accounts) == 0 {
			accounts = []string{"default"}
		}
		provider := run.NewObject()
		kept.Set(sub.Name, provider)
		for _, account := range accounts {
			var last *run.Object
			if provider := old.Dict(sub.Name); provider != nil {
				last = provider.Dict(account)
			}
			if last == nil {
				last = run.NewObject()
			}
			checked, dated := finite(last.Get("checked_at"))
			ends, ending := finite(last.Get("ends"))
			if !dated || now-checked < 0 || now-checked >= 3600 || ending && ends-now <= 7*86400 {
				last = last.Copy()
				if answer := logins.Ask(sub.Harness, account); answer != nil {
					run.SetAll(last, "email", answer.Get("email"), "ends", answer.Get("ends"), "plan", answer.Get("plan"))
				}
				last.Set("checked_at", run.Float(now))
			}
			provider.Set(account, last)
		}
	}
	if !run.Equal(old, kept) {
		tmp := filepath.Join(state(), "logins.tmp")
		if err := os.WriteFile(tmp, []byte(run.Encode(kept)+"\n"), 0o666); err != nil {
			return nil, err
		}
		if err := os.Rename(tmp, filepath.Join(state(), "logins.json")); err != nil {
			return nil, err
		}
	}
	return kept, nil
}
