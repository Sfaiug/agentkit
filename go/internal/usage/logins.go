package usage

import (
	"agentkit/internal/config"
	"agentkit/internal/run"
	"agentkit/internal/terminal"
)

// asked is that provider's reading, Python's usage._probe_gently: its one login asked gently, or
// where it lists accounts each of them, every one under its own lock, cadence and mark
// (source.key), kept under the provider, whose own fields are then the account a worker turn runs
// on next (flagAccounts).
func asked(sources []source, name string, models map[string]config.Model) *run.Object {
	now, read := clock(), run.NewObject()
	for _, src := range sources {
		if src.Name == name && src.account == "" {
			return gently(src)
		} else if src.Name == name {
			read.Set(src.account, withoutPast(gently(src), now, "the adapter"))
		}
	}
	prov := fields("provider", name, "accounts", read)
	flagAccounts(name, prov, now, models)
	return prov
}

// accounts is what config.toml lists of that provider's accounts, as its sources ask them: none
// for a provider of one login.
func accounts(sources []source, name string) (listed []string) {
	for _, src := range sources {
		if src.Name == name && src.account != "" {
			listed = append(listed, src.account)
		}
	}
	return listed
}

// laidOut gives a provider's record an entry for each account config.toml lists, the snapshot's
// where it holds one, else this read's own, each past its reset dropped, Python's usage._store;
// and is the record the read's counted resets go on: the account it asked about, else the provider.
func laidOut(prov, mine *run.Object, listed []string, now float64) *run.Object {
	if len(listed) == 0 {
		return prov
	}
	theirs, ours := object(prov.Get("accounts")), object(mine.Get("accounts"))
	accounts := run.NewObject()
	for _, account := range listed {
		record := object(theirs.Get(account))
		if len(record.Keys()) == 0 {
			record = object(ours.Get(account))
		}
		accounts.Set(account, current(record, now))
	}
	prov.Set("accounts", accounts)
	if asked, ok := accounts.Get(mine.Str("account")).(*run.Object); ok {
		return asked
	}
	return prov
}

// A login is one subscription as `ak usage` shows it, Python's usage._accounts: a provider of one
// login, or each account of one listing several, labelled as a person reads it, under the
// account it is listed as, "" for a provider's one login.
type login struct {
	label, provider, account string
	prov                     *run.Object
}

func (r *Readings) logins() []login {
	var found []login
	for _, name := range r.providers.Keys() {
		prov := object(r.providers.Get(name))
		accounts, ok := prov.Get("accounts").(*run.Object)
		if !ok || len(accounts.Keys()) == 0 {
			found = append(found, login{name, name, "", prov})
			continue
		}
		listed, _ := config.Accounts(name)
		for _, account := range accounts.Keys() {
			found = append(found, login{config.AccountLabel(listed, account, name), name, account, object(accounts.Get(account))})
		}
	}
	return found
}

// LabelCells is how wide the widest account's label is, which its row keeps whole: `acme I…`
// would not say which one it is.
func (r *Readings) LabelCells() int {
	widest := 0
	for _, each := range r.logins() {
		if each.label != each.provider {
			widest = max(widest, terminal.Cells(each.label))
		}
	}
	return widest
}
