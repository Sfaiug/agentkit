package matrix

import (
	"errors"

	"agentkit/internal/boards"
	"agentkit/internal/config"
	"agentkit/internal/quality"
	"agentkit/internal/run"
)

// ErrPriced is an answer some role prices off ak's own runs: Go draws costs in board dollars
// alone, so drawing it is Python's.
var ErrPriced = errors.New("a role is priced in what ak's own runs measured")

// configRoles is the config's word for each role ak answers, the one ak's runs measure it under.
var configRoles = map[string]string{"orchestrate": "orchestrator", "execute": "executor", "review": "reviewer"}

// Shares is what ak's own runs measured each offered model's worker roles to take of a week,
// {model: {effort: {role: share}}}, at the listed prices of the boards as cached (shares).
func Shares() (*run.Object, error) { return shares(boards.Cached()) }

// Answer is each role's answer over rows (quality.Answer), its rows priced at shares as Python's
// matrix._costs prices them, in one unit per role.  ak's own runs price a role and never rate it:
// asked on 5 Nov 2026 what their runs should decide, the owner answered "Costs only", as quality
// comes from the boards.
//
// A row an offered model is, found as its release alone, costs the share that model measured at
// its effort, the first such model that measured one; any other costs its board dollars times the
// pooled shares over board dollars of its provider's measured rows (the model's, else the one its
// board's maker names), else of every measured row.  A role without a measured row stays in board
// dollars; one with is in money, each share times its provider's price, only where every provider
// of the lineup has a price.
func Answer(rows []quality.Row, compared map[string]bool, shares *run.Object) (map[string]*quality.Said, error) {
	names, err := config.Offered()
	if err != nil {
		return nil, err
	}
	models, err := config.Models()
	if err != nil {
		return nil, err
	}
	subs, err := config.Subscriptions()
	if err != nil {
		return nil, err
	}
	monthly := map[string]*float64{}
	for _, sub := range subs {
		monthly[sub.Name] = sub.Price
	}
	makers := map[string]string{"": ""} // a row whose board names no maker names no provider
	for _, row := range rows {
		if _, named := makers[row.Maker]; !named {
			if makers[row.Maker], err = config.Company(row.Maker); err != nil {
				return nil, err
			}
		}
	}
	// the lineup's releases, each under the name its last row gives it
	var releases []*boards.Release
	named := map[string]*boards.Release{}
	for _, row := range rows {
		if named[row.Release] == nil {
			named[row.Release] = &boards.Release{Slug: row.Release}
			releases = append(releases, named[row.Release])
		}
		named[row.Release].Name = row.Name
	}
	index := indexOf(releases)
	alone := map[string]string{} // each offered model's release, where found finds one alone
	for _, name := range names {
		slugs := map[string]bool{}
		for _, one := range found(index, models[name].ID) {
			slugs[one.release.Slug] = true
		}
		if len(slugs) == 1 {
			for slug := range slugs {
				alone[name] = slug
			}
		}
	}
	price := func(role string, rows []quality.Row, rated []*quality.Rating) string {
		measuredShare := func(name, effort string) (float64, bool) {
			// a row without an effort measured none: ak's runs count only those naming theirs
			if efforts := shares.Dict(name); effort != "" && efforts != nil && efforts.Dict(effort) != nil {
				return run.Num(efforts.Dict(effort).Get(configRoles[role]))
			}
			return 0, false
		}
		type place struct{ release, effort string }
		type source struct{ name, provider string }
		sources := map[place]source{}
		for _, row := range rows {
			var matches []source
			for _, name := range names {
				if alone[name] == row.Release {
					matches = append(matches, source{name, models[name].Provider})
				}
			}
			chosen := source{provider: makers[row.Maker]}
			if len(matches) > 0 {
				chosen = matches[0]
			}
			for _, match := range matches {
				if _, measured := measuredShare(match.name, row.Effort); measured {
					chosen = match
					break
				}
			}
			sources[place{row.Release, row.Effort}] = chosen
		}
		measured := map[place]float64{}
		var providers []string
		pools := map[string]*[2]float64{} // each provider's measured shares and their board dollars
		for _, row := range rated {
			at := place{row.Release, row.Effort}
			share, ok := measuredShare(sources[at].name, row.Effort)
			if !ok {
				continue
			}
			measured[at] = share
			if row.BoardCost != nil && *row.BoardCost > 0 {
				provider := sources[at].provider
				if pools[provider] == nil {
					providers, pools[provider] = append(providers, provider), &[2]float64{}
				}
				pools[provider][0] += share
				pools[provider][1] += *row.BoardCost
			}
		}
		if len(measured) == 0 {
			return "board_dollars"
		}
		var poolShares, poolDollars []float64
		for _, provider := range providers {
			poolShares, poolDollars = append(poolShares, pools[provider][0]), append(poolDollars, pools[provider][1])
		}
		pooled := quality.Sum(poolShares) / quality.Sum(poolDollars)
		money := true
		for _, chosen := range sources {
			money = money && monthly[chosen.provider] != nil
		}
		for _, row := range rated {
			at := place{row.Release, row.Effort}
			provider := sources[at].provider
			factor, converts := pooled, len(providers) > 0
			row.CostRule = "global"
			if pool := pools[provider]; pool != nil {
				factor, row.CostRule = pool[0]/pool[1], "provider"
			}
			// Without board dollars or a measured conversion, no same-unit estimate exists.
			row.Cost = nil
			if share, ok := measured[at]; ok {
				row.Cost, row.CostRule = &share, "measured"
			} else if row.BoardCost != nil && converts {
				cost := *row.BoardCost * factor
				row.Cost = &cost
			}
			if money && row.Cost != nil {
				cost := *row.Cost * *monthly[provider]
				row.Cost = &cost
			}
		}
		if money {
			return "money"
		}
		return "share"
	}
	return quality.Answer(rows, compared, price), nil
}

// Drawn is ErrPriced where a role of answer is priced off ak's own runs, which Go does not draw.
func Drawn(answer map[string]*quality.Said) error {
	for _, said := range answer {
		if said.CostUnit != "board_dollars" {
			return ErrPriced
		}
	}
	return nil
}
