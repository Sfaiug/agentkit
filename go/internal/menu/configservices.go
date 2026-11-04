package menu

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/notify"
	"agentkit/internal/run"
)

// ConfigServices reads the saved Discord and cloud status without contacting either service.
func ConfigServices(now time.Time) (discord, cloud string) {
	secret := func(name string) string {
		data, _ := os.ReadFile(filepath.Join(config.Home(), "secrets", name))
		return strings.TrimFunc(string(data), config.Space)
	}
	discord = "not connected"
	if hook := []rune(secret("discord_webhook")); len(hook) > 0 {
		var parts []string
		if user := secret("discord_user_id"); user != "" {
			if name := notify.Pinged(user); name != "" {
				parts = append(parts, "@"+name)
			} else {
				id := []rune(user)
				parts = append(parts, "id …"+string(id[max(0, len(id)-4):]))
			}
		}
		discord = strings.Join(append(parts, "webhook …"+string(hook[max(0, len(hook)-6):])), " · ")
	}
	return discord, cloudValue(now)
}

func cloudValue(now time.Time) string {
	active, cap := config.CloudBudget()
	ledger, _ := run.ReadJSON(filepath.Join(config.Home(), "state", "google-cloud-ledger.json"))
	if !cloudLedger(ledger) {
		ledger = nil
	}
	if active {
		if ledger != nil {
			answered, _ := ledger.Num("answered")
			if answered != 0 && time.Unix(int64(answered), 0).UTC().Format("2006-01") == now.UTC().Format("2006-01") {
				up := 0
				for _, key := range ledger.Dict("machines").Keys() {
					if !ledger.Dict("machines").Dict(key).Has("from") {
						up++
					}
				}
				spent, _ := ledger.Num("spent")
				return fmt.Sprintf("on · €%.2f of €%.6g this month · %d %s up", spent, cap, up, machineWord(up))
			}
		}
		return "on · spend unknown"
	}
	if ledger != nil {
		if left := len(ledger.Dict("machines").Keys()); left > 0 {
			return fmt.Sprintf("off · %d %s going once idle", left, machineWord(left))
		}
	}
	return "off"
}

func machineWord(count int) string {
	if count == 1 {
		return "machine"
	}
	return "machines"
}

// A partial or corrupt ledger never supplies an amount to the screen (google_cloud._ledger).
func cloudLedger(ledger *run.Object) bool {
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
