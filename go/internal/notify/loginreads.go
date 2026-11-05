package notify

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/host"
	"agentkit/internal/lock"
	"agentkit/internal/run"
)

// QuietLogins refreshes Python's logins.json under its record lock. A failed read
// keeps the last answer and only dates the ask; a login due a reminder stays Python's.
func QuietLogins() (bool, error) {
	subs, err := config.Subscriptions()
	if err != nil {
		return false, err
	}
	if err := config.EnsureDirs(); err != nil {
		return false, err
	}
	held, err := lock.Wait(context.Background(), filepath.Join(state(), ".logins.lock"))
	if err != nil {
		return false, err
	}
	defer held.Close()
	old, err := run.ReadJSON(filepath.Join(state(), "logins.json"))
	if errors.Is(err, run.ErrLoneSurrogate) {
		return false, ErrUnread
	}
	if old == nil {
		old = run.NewObject()
	}
	kept, quiet, now := run.NewObject(), true, clock()
	for _, sub := range subs {
		accounts, err := config.Accounts(sub.Name)
		if err != nil {
			return false, err
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
				if answer := loginEnd(sub.Harness, account); answer != nil {
					run.SetAll(last, "email", answer.Get("email"), "ends", answer.Get("ends"), "plan", answer.Get("plan"))
				}
				last.Set("checked_at", run.Float(now))
			}
			provider.Set(account, last)
			if ends, known := finite(last.Get("ends")); known && ends-now <= 3*86400 {
				quiet = false
			}
		}
	}
	if !run.Equal(old, kept) {
		tmp := filepath.Join(state(), "logins.tmp")
		if err := os.WriteFile(tmp, []byte(run.Encode(kept)+"\n"), 0o666); err != nil {
			return false, err
		}
		if err := os.Rename(tmp, filepath.Join(state(), "logins.json")); err != nil {
			return false, err
		}
	}
	return quiet, nil
}

func loginEnd(harness, account string) *run.Object {
	adapter, err := config.Adapter(harness)
	if errors.Is(err, config.ErrNoAdapterDir) {
		adapter, err = config.ShippedAdapter(harness)
	}
	if err != nil || harness == "" {
		return nil
	}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, adapter, "login-end")
	if account == "default" {
		account = ""
	}
	cmd.Env = append(os.Environ(), "AGENTKIT_ACCOUNT="+account)
	cmd.WaitDelay = time.Second
	host.AdapterCall(cmd)
	out, err := cmd.Output()
	if err != nil {
		return nil
	}
	value, err := run.Decode(out)
	answer, ok := value.(*run.Object)
	if err != nil || !ok {
		return nil
	}
	for _, key := range []string{"email", "plan"} {
		if value := answer.Get(key); value != nil {
			if text, ok := value.(string); !ok || text == "" {
				return nil
			}
		}
	}
	if answer.Get("ends") != nil {
		if _, ok := finite(answer.Get("ends")); !ok {
			return nil
		}
	}
	return answer
}
