package menu

import (
	"cmp"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/logins"
	"agentkit/internal/terminal"
	"agentkit/internal/usage"
)

// Cells is each subscription as the grid draws it from what usage.json and logins.json hold as they
// stand, nothing probed: by company colour, red through violet and the near-greys last, a free
// provider having none.
func Cells(now time.Time) ([]Cell, error) {
	subs, err := config.Subscriptions()
	if err != nil {
		return nil, err
	}
	readings, err := usage.Cached()
	if err != nil {
		return nil, err
	}
	type shown struct {
		sub          config.Subscription
		name, colour string
		grey         bool
		place        float64
	}
	var rows []shown
	for _, sub := range subs {
		if sub.Mode == "free" {
			continue
		}
		name, colour, err := config.ProviderLook(sub.Name)
		if err != nil {
			return nil, err
		}
		// a provider coloured nowhere is in the accent
		ownName, ownColour := harness.Company(sub.Name)
		grey, place := hue(cmp.Or(colour, ownColour, "#"+terminal.RGB("accent")))
		rows = append(rows, shown{sub, cmp.Or(name, ownName), cmp.Or(colour, ownColour, "accent"), grey, place})
	}
	slices.SortStableFunc(rows, func(a, b shown) int {
		if a.grey != b.grey {
			if b.grey {
				return -1
			}
			return 1
		}
		return cmp.Compare(a.place, b.place)
	})
	var cells []Cell
	for _, each := range rows {
		accounts, err := config.Accounts(each.sub.Name)
		if err != nil {
			return nil, err
		}
		if len(accounts) == 0 {
			accounts = []string{""} // the provider's one login
		}
		for _, account := range accounts {
			left, said := readings.Cell(each.sub.Name, account)
			login := logins.Of(each.sub.Name, account)
			cell := Cell{Label: config.AccountLabel(accounts, account, each.name), Left: left, Said: said, Ends: logins.Ending(login, now), Provider: each.sub.Name,
				Account: account, Company: cmp.Or(harness.Heading(each.sub.Name), each.name), Colour: each.colour,
				Harness: logins.Harness(each.sub),
				Held:    readings.InHand(each.sub.Name, account), Notes: readings.Detail(each.sub.Name, account)}
			if login != nil {
				cell.Email, cell.Plan = login.Str("email"), config.PlanName(cell.Harness, login.Str("plan"))
			}
			cells = append(cells, cell)
		}
	}
	return cells, nil
}

// hue is where a colour sorts: red through violet by its hue, the near-greys by how light they are.
func hue(colour string) (grey bool, place float64) {
	var channel [3]float64
	for i := range channel {
		value, _ := strconv.ParseUint(colour[1+2*i:3+2*i], 16, 8)
		channel[i] = float64(value) / 255
	}
	high, low := slices.Max(channel[:]), slices.Min(channel[:])
	if high == 0 || (high-low)/high < 0.15 {
		return true, -high
	}
	span := high - low
	switch high {
	case channel[0]:
		place = (channel[1] - channel[2]) / span
	case channel[1]:
		place = 2 + (channel[2]-channel[0])/span
	default:
		place = 4 + (channel[0]-channel[1])/span
	}
	return false, math.Mod(place/6+1, 1)
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
