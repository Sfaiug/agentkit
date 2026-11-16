package menu

import (
	"cmp"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/logins"
	"agentkit/internal/usage"
)

// Cells is each subscription as the grid draws it from what usage.json and logins.json hold as they
// stand, nothing probed: in the order config.toml names their providers, a free provider having
// none.
func Cells(now time.Time) ([]Cell, error) {
	subs, err := config.Subscriptions()
	if err != nil {
		return nil, err
	}
	readings, err := usage.Cached()
	if err != nil {
		return nil, err
	}
	var cells []Cell
	for _, sub := range subs {
		if sub.Mode == "free" {
			continue
		}
		name, err := harness.ProviderName(sub.Name)
		if err != nil {
			return nil, err
		}
		accounts, err := config.Accounts(sub.Name)
		if err != nil {
			return nil, err
		}
		if len(accounts) == 0 {
			accounts = []string{""} // the provider's one login
		}
		for _, account := range accounts {
			left, said := readings.Cell(sub.Name, account)
			login := logins.Of(sub.Name, account)
			label, err := harness.SubscriptionName(sub.Name, account)
			if err != nil {
				return nil, err
			}
			cell := Cell{Label: label, Left: left, Said: said, Ends: logins.Ending(login, now), Provider: sub.Name,
				Account: account, Company: cmp.Or(harness.Heading(sub.Name), name),
				Harness: logins.Harness(sub),
				Held:    readings.InHand(sub.Name, account), Notes: readings.Detail(sub.Name, account)}
			if login != nil {
				cell.Email, cell.Plan = login.Str("email"), config.PlanName(cell.Harness, login.Str("plan"))
			}
			cells = append(cells, cell)
		}
	}
	return cells, nil
}

// Standing is the worker token's note while the ak screen shows it, from config.TokenWarn days out and once
// it has expired, else "": the first declared token whose file holds one (watch.token_standing).
func Standing(now time.Time) (string, error) {
	tokens, err := config.WorkerTokens()
	if err != nil {
		return "", err
	}
	for _, token := range tokens {
		path := filepath.Join(config.Home(), "secrets", token[1])
		info, statErr := os.Stat(path)
		data, readErr := os.ReadFile(path)
		if statErr != nil || readErr != nil || strings.TrimSpace(string(data)) == "" {
			continue
		}
		ends := info.ModTime().Add(config.TokenLife * 24 * time.Hour)
		when := ends.Format("2006-01-02")
		if !now.Before(ends) {
			return token[0] + " worker token expired " + when, nil
		}
		if days := int(ends.Sub(now) / (24 * time.Hour)); days <= config.TokenWarn {
			return fmt.Sprintf("%s worker token expires %s (in %d days)", token[0], when, days), nil
		}
		return "", nil
	}
	return "", nil
}
