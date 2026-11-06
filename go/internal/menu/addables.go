package menu

import (
	"cmp"
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/harness"
)

// An Addable is a choice of `+ add a subscription`'s first list, by the label it is offered under.
type Addable struct {
	Label, Provider string
	Host            string   // a harness that runs any provider it can log in to, which opens its own list
	Accounts        []string // another subscription's: its provider's accounts, the new one last
}

// Addables is `+ add a subscription`'s first list (menu.config_add_provider): each provider the
// shipped default has and the config lacks, by its company and the harness it runs on, but those
// shipped on a host; each host, by its label, standing in for those; then, as the name it will get
// (`ChatGPT II`), another subscription of each provider the config has, its account fresh, where its
// harness keeps more than one login.
func Addables(fresh string) ([]Addable, error) {
	has, lacks, err := config.ProviderNames()
	if err != nil {
		return nil, err
	}
	hosts, hostLabels := config.ProviderHosts()
	var shipped []string
	for _, provider := range lacks {
		// the shipped default's alone: a model of the config naming a provider it lacks runs nowhere
		if !slices.ContainsFunc(config.ShippedHarnesses(provider), func(on string) bool { return slices.Contains(hosts, on) }) {
			shipped = append(shipped, provider)
		}
	}
	var makers []string
	for _, provider := range shipped {
		company, _ := harness.Company(provider)
		makers = append(makers, cmp.Or(harness.Maker(provider), company, titled(provider)))
	}
	choices := byLabel(shipped, makers)
	for _, host := range hosts {
		if !slices.ContainsFunc(choices, func(one Addable) bool { return one.Label == hostLabels[host] }) {
			choices = append(choices, Addable{Label: hostLabels[host], Host: host})
		}
	}
	var names []string
	for _, provider := range has {
		name, _, err := config.ProviderLook(provider)
		if err != nil {
			return nil, err
		}
		company, _ := harness.Company(provider)
		names = append(names, cmp.Or(name, company, titled(provider)))
	}
	for _, more := range byLabel(has, names) {
		harnesses, err := config.ProviderHarnesses(more.Provider)
		if err != nil {
			return nil, err
		}
		if len(harnesses) > 0 && config.OneLogin(harnesses[0]) {
			continue // its login would be refused
		}
		accounts, err := config.Accounts(more.Provider)
		if err != nil {
			return nil, err
		}
		if len(accounts) == 0 {
			accounts = []string{config.DefaultAccount} // its usual login
		}
		more.Accounts = append(accounts, fresh)
		more.Label = config.AccountLabel(more.Accounts, fresh, more.Label)
		choices = append(choices, more)
	}
	return choices, nil
}

// byLabel is each of providers by its label, one two of them share followed by the provider itself,
// so the one picked is always the one it says (menu._by_label).
func byLabel(providers, labels []string) []Addable {
	var named []Addable
	for i, provider := range providers {
		text := labels[i]
		if slices.Index(labels, text) != i || slices.Index(labels[i+1:], text) >= 0 {
			text += " (" + provider + ")"
		}
		named = append(named, Addable{Label: text, Provider: provider})
	}
	return named
}
