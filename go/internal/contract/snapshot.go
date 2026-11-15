package contract

import (
	"cmp"
	"math"
	"os"
	"path/filepath"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/loop"
	"agentkit/internal/run"
	"agentkit/internal/usage"
)

// login is the login the check runs on that provider, "" for the usual one: the first account
// config.toml lists of it, which smoke_home lists only for a subscription it lent by name.
// SMOKE_LOGIN=usual names the usual one, where smoke.sh's checks run their harnesses' own
// headless commands.
func login(provider string) string {
	if os.Getenv("SMOKE_LOGIN") == "usual" {
		return ""
	}
	accounts, _ := config.Accounts(provider)
	if len(accounts) == 0 {
		return ""
	}
	return accounts[0]
}

// providers is the reading of each provider a usage snapshot holds, of the login the check runs
// on it where it lists accounts; none where it says nothing.
func providers(path string) *run.Object {
	found := run.NewObject()
	data, err := os.ReadFile(path)
	if err != nil {
		return found
	}
	decoded, _ := run.Decode(data)
	snapshot, _ := decoded.(*run.Object)
	if snapshot == nil {
		return found
	}
	read, _ := snapshot.Get("providers").(*run.Object)
	if read == nil {
		return found
	}
	for _, name := range read.Keys() {
		record, _ := read.Get(name).(*run.Object)
		if record != nil && record.Dict("accounts") != nil {
			record, _ = record.Dict("accounts").Get(cmp.Or(login(name), config.DefaultAccount)).(*run.Object)
		}
		if record != nil {
			found.Set(name, record)
		}
	}
	return found
}

// spentUntil is when the window spending model, the check's entry name, comes back, and whether
// one does: on the snapshot's reading, else, where that holds no meters, on the same login's in
// the caller's own cache, windows already reset dropped, as a sandbox's empty read shares the
// host's cadence.  Another subscription cannot answer for it.
func spentUntil(model config.Model, name, snapshot string) (string, bool) {
	models, err := config.Entries()
	if err != nil {
		models = map[string]config.Model{}
	}
	models[name] = model
	read := providers(snapshot)
	until, spent := usage.Snapshot(read, models).SpentUntil(name)
	if !spent {
		if record, _ := read.Get(model.Provider).(*run.Object); record != nil && record.Truthy("meters") {
			return "", false
		}
		read = providers(cache())
		record, _ := read.Get(model.Provider).(*run.Object)
		read.Set(model.Provider, usage.WithoutPast(cmp.Or(record, run.NewObject()), "the host cache"))
		if until, spent = usage.Snapshot(read, models).SpentUntil(name); !spent {
			return "", false
		}
	}
	if at, ok := run.Num(until); ok && at != 0 {
		return when(at), true
	}
	return "unknown", true
}

// caller is the home of whoever runs the check: smoke.sh's sandbox names its caller's.
func caller() string {
	return cmp.Or(os.Getenv("SMOKE_CALLER_HOME"), config.UserHome())
}

// cache is the usage snapshot of the caller's own ak.
func cache() string {
	return filepath.Join(caller(), ".agentkit", "state", "usage.json")
}

// refusal is why the turn of model in out, which exited code, proves nothing, "" where it may:
// its provider's window spent, which the check's snapshot keeps for its later checks, never the
// host's cache, or the provider down in its harness's own words, which spends no window.
func refusal(model config.Model, code int, out, snapshot string) (string, error) {
	if code == 0 {
		return "", nil
	}
	answer, said := loop.Refusal(out, model.Harness)
	word := harness.Heard(model.Harness, harness.Spent, said)
	if word == "" {
		// A provider's 500s for six minutes held the install on 5 Nov 2026.
		if down := harness.Heard(model.Harness, harness.Outage, said); down != "" {
			return "the provider was down (" + down + ")", nil
		}
		return "", nil
	}
	read := providers(snapshot)
	record, _ := read.Get(model.Provider).(*run.Object)
	record, until := usage.Parked(cmp.Or(record, run.NewObject()), said)
	read.Set(model.Provider, record)
	if err := os.WriteFile(snapshot, []byte(run.Line(run.Fields("providers", read))), 0o666); err != nil {
		return "", err
	}
	return cmp.Or(strings.TrimFunc(answer, config.Space), word) + "; comes back " + when(until), nil
}

// when is that moment as the check's lines say it, in local time and its zone.
func when(at float64) string {
	return time.Unix(int64(math.Floor(at)), 0).Format("2006-01-02 15:04:05 MST")
}
