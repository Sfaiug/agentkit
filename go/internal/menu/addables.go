package menu

import (
	"slices"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/terminal"
)

// An Addable is a row of `+ add a subscription`: the company it is under and the name it is offered as.
type Addable struct {
	Company, Label, Provider string
	Host                     string   // a harness that runs any provider it can log in to, which opens its own list
	Accounts                 []string // another subscription's: its provider's accounts, the new one last
}

// Addables is `+ add a subscription`'s rows (menu.config_add_provider), each under its company as
// Subscriptions heads it (harness.Heading) and named as Subscriptions will name it once added: first,
// in the config's order, another subscription of each provider it has (`ChatGPT II`), its account
// fresh, where its harness keeps more than one login; then each provider the shipped default has and
// the config lacks, but those shipped on a host; then `another provider` under each host, standing in
// for those.
func Addables(fresh string) ([]Addable, error) {
	has, lacks, err := config.ProviderNames()
	if err != nil {
		return nil, err
	}
	var choices []Addable
	for _, provider := range has {
		harnesses, err := config.ProviderHarnesses(provider)
		if err != nil {
			return nil, err
		}
		if len(harnesses) > 0 && config.OneLogin(harnesses[0]) {
			continue // its login would be refused
		}
		name, err := harness.ProviderName(provider)
		if err != nil {
			return nil, err
		}
		accounts, err := config.Accounts(provider)
		if err != nil {
			return nil, err
		}
		if len(accounts) == 0 {
			accounts = []string{config.DefaultAccount} // its usual login
		}
		accounts = append(accounts, fresh)
		choices = append(choices, Addable{Company: harness.Heading(provider, name),
			Label: config.AccountLabel(accounts, fresh, name), Provider: provider, Accounts: accounts})
	}
	hosts, hostLabels := config.ProviderHosts()
	for _, provider := range lacks {
		// the shipped default's alone: a model of the config naming a provider it lacks runs nowhere
		if !slices.ContainsFunc(config.ShippedHarnesses(provider), func(on string) bool { return slices.Contains(hosts, on) }) {
			name := harness.Company(provider)
			choices = append(choices, Addable{Company: harness.Heading(provider, name), Label: name, Provider: provider})
		}
	}
	for _, host := range hosts {
		choices = append(choices, Addable{Company: hostLabels[host], Label: "another provider", Host: host})
	}
	return choices, nil
}

// AddablesPage is `+ add a subscription` drawn (menu.config_add_provider): each of choices under its
// company, bold and flush left as Subscriptions heads one, on a line of no row; a name wider than the
// layout wraps, each line of a row its row's.  The row at is lit unless the pointer is away, and paged
// so it is shown as matrix_key pages it (PageFrame).
func AddablesPage(s terminal.Screen, title string, choices []Addable, at, top int, away bool) PageFrame {
	room, keys := s.LayoutWidth(), pageKeys(s, "add")
	var body []string
	var lines []pageEntry
	for row, choice := range choices {
		for _, part := range terminal.Wrap(choice.Company, room) {
			body, lines = append(body, s.Bold(part)), append(lines, pageEntry{-1, -1})
		}
		for line, part := range terminal.Wrap(choice.Label, room-2) {
			part = "  " + part
			if row == at && !away {
				part = s.Band(s.Highlight(part, line == 0), room)
			}
			body, lines = append(body, part), append(lines, pageEntry{row, -1})
		}
	}
	keyLines := keyLine(s, keys, s.Width(), "")
	page := max(1, s.Height()-5-len(keyLines))
	top = pageTop(lines, pageEntry{at, -1}, top, page)
	drawn := Panel(s, title, time.Now().Format("15:04"), body[top:min(top+page, len(body))], keys)
	return PageFrame{Lines: drawn, Top: top, at: pageEntry{at, -1}, page: page, lines: lines, width: room,
		keySpots: spotted(keyLines, len(drawn)-len(keyLines)+1, s.LayoutWidth())}
}
