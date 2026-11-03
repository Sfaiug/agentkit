package harness

import (
	"os"
	"path/filepath"

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

// museStem is what one login's quota record and probe cache are named after.
func museStem(account string) string {
	if account != "" {
		return "usage-meta." + account
	}
	return "usage-meta"
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

// museUsageRecorded is the quota imported from a refused turn's adapter report: each meter is trusted
// for at most its own window, as the adapter's `usage` verb trusts it.
func museUsageRecorded(state string, now float64) []*run.Object {
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
