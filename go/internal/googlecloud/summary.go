package googlecloud

import (
	"fmt"
	"path/filepath"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// Summary is the cloud's switch and this month's spend as the tick's meter left it, asking
// Google nothing, `count` adding the machines up or going (google_cloud.summary): money never read
// this month is never shown.
func Summary(count bool) string {
	active, cap := config.CloudBudget()
	ledger, _ := run.ReadJSON(filepath.Join(config.Home(), "state", "google-cloud-ledger.json"))
	if !readable(ledger) {
		ledger = nil
	}
	if !active {
		if ledger == nil || !count || len(ledger.Dict("machines").Keys()) == 0 {
			return "off"
		}
		left := len(ledger.Dict("machines").Keys())
		return fmt.Sprintf("off · %d %s going once idle", left, machineWord(left))
	}
	if ledger == nil {
		return "on · spend unknown"
	}
	answered, _ := ledger.Num("answered")
	spent, _ := ledger.Num("spent")
	at, err := now()
	month := func(seconds float64) string { return time.Unix(int64(seconds), 0).UTC().Format("2006-01") }
	if answered == 0 || err != nil || month(answered) != month(at) {
		return "on · spend unknown"
	}
	said := fmt.Sprintf("on · €%.2f of €%.6g this month", spent, cap)
	if count {
		up := 0
		for _, key := range ledger.Dict("machines").Keys() {
			if !ledger.Dict("machines").Dict(key).Has("from") {
				up++
			}
		}
		said += fmt.Sprintf(" · %d %s up", up, machineWord(up))
	}
	return said
}

func machineWord(count int) string {
	if count == 1 {
		return "machine"
	}
	return "machines"
}

// readable is whether the meter holds only amounts ak could have written: a partial or corrupt
// one never supplies an amount (google_cloud._ledger).
func readable(ledger *run.Object) bool {
	amount := func(value any) bool {
		number, ok := run.Num(value)
		return ok && number >= 0 && number < 1e12
	}
	if ledger == nil || ledger.Dict("machines") == nil || !amount(ledger.Get("answered")) || !amount(ledger.Get("spent")) {
		return false
	}
	for _, key := range ledger.Dict("machines").Keys() {
		one := ledger.Dict("machines").Dict(key)
		if one == nil || !amount(one.Get("price")) || !amount(one.Get("until")) || one.Has("from") && !amount(one.Get("from")) {
			return false
		}
	}
	return true
}
