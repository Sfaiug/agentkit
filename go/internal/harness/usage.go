package harness

import (
	"os"
	"path/filepath"

	"agentkit/internal/config"
	"agentkit/internal/config/adapters"
	"agentkit/internal/run"
)

// UsageTaken is when an adapter that strips its probe's timestamp measured what data says, Python's
// plugin `usage_extra`: nil where nothing recognises the response, which must not look newly measured.
func UsageTaken(name string, data *run.Object, state string) any {
	if hook := plugins[name].usageTaken; hook != nil {
		return hook(data, state)
	}
	return nil
}

// UsageRecorded is the meters a harness wrote down when it refused a run and that still stand,
// Python's plugin `usage_recorded`: a file and no request.
func UsageRecorded(name, state string, now float64) []*run.Object {
	if hook := plugins[name].usageRecorded; hook != nil {
		return hook(state, now)
	}
	return nil
}

// RecordTurn keeps what a turn in out reported of its refusal once its box closed, Python's plugin
// `record_turn`: the box writes none of ak's records itself.
func RecordTurn(name, out, state, account string) {
	if hook := plugins[name].recordTurn; hook != nil {
		hook(out, state, account)
	}
}

// museStem is what one login's refusal record and probe cache are named after.
func museStem(account string) string {
	if account != "" {
		return "usage-meta." + account
	}
	return "usage-meta"
}

// museRecordTurn moves the report to the login's own record; left behind, a retry whose box cannot
// start would date an earlier refusal as new.
func museRecordTurn(out, state, account string) {
	report := filepath.Join(out, adapters.RefusalReport)
	data, err := os.ReadFile(report)
	if err != nil {
		return
	}
	value, err := run.Decode(data)
	if err != nil || os.MkdirAll(state, 0o777) != nil {
		return
	}
	if os.WriteFile(filepath.Join(state, museStem(account)+".json"), []byte(run.Line(value)+"\n"), 0o666) == nil {
		os.Remove(report)
	}
}

// museUsageTaken matches the response to the file it came from before carrying that file's age: an
// account's response names it, and is matched against that account's files alone.
func museUsageTaken(data *run.Object, state string) any {
	account, _ := data.Get("account").(string)
	for _, suffix := range []string{".json", "-probe.json"} {
		path := filepath.Join(state, museStem(account)+suffix)
		cached, err := run.ReadJSON(path)
		if err != nil || cached == nil || !run.Equal(cached.Get("meters"), data.Get("meters")) || !run.Equal(cached.Get("error"), data.Get("error")) {
			continue
		}
		if suffix == "-probe.json" {
			if at, ok := run.Num(cached.Get("fetched_at")); ok {
				return run.Float(at)
			}
			return nil
		}
		if info, err := os.Stat(path); err == nil {
			return run.Float(float64(info.ModTime().UnixNano()) / 1e9)
		}
	}
	return nil
}

// museUsageRecorded is the meters imported from a refused turn's adapter report: each meter is trusted
// for at most its own window, as the adapter's `usage` verb trusts it.  Where `[providers.meta]`
// lists accounts each login keeps a record of its own and nothing here says which is being read:
// none is applied, and each reaches its own reading through that account's `usage` verb.
func museUsageRecorded(state string, now float64) []*run.Object {
	if accounts, _ := config.Accounts("meta"); len(accounts) > 0 {
		return nil
	}
	path := filepath.Join(state, museStem("")+".json")
	info, err := os.Stat(path)
	if err != nil {
		return nil
	}
	cached, err := run.ReadJSON(path)
	if err != nil || cached == nil {
		return nil
	}
	age := now - float64(info.ModTime().UnixNano())/1e9
	var found []*run.Object
	for _, each := range cached.List("meters") {
		meter, _ := each.(*run.Object)
		if meter == nil {
			return nil
		}
		resets, known := run.Num(meter.Get("resets_at"))
		window, sized := run.Num(meter.Get("window_secs"))
		if !known || !sized {
			return nil
		}
		if resets > now && window > age {
			found = append(found, meter)
		}
	}
	return found
}
