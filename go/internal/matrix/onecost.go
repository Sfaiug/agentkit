package matrix

import (
	"agentkit/internal/boards"
	"agentkit/internal/config"
	"agentkit/internal/quality"
	"agentkit/internal/run"
	"agentkit/internal/usage"
)

// Answer is each role's answer over rows (quality.Answer), every role's rows priced in one unit
// off what ak's own runs measured (measured), as Python's matrix._costs prices them.  ak's own
// runs price a role and never rate it: asked on 5 Nov 2026 what their runs should decide, the
// owner answered "Costs only", as quality comes from the boards.
func Answer(rows []quality.Row, compared map[string]bool, measured *Measures) (map[string]*quality.Said, error) {
	names, err := config.Offered()
	if err != nil {
		return nil, err
	}
	models, err := config.Models()
	if err != nil {
		return nil, err
	}
	costs, err := measure(rows, measured, names, models)
	if err != nil {
		return nil, err
	}
	runs := map[[2]string]bool{} // what a configured model runs: its harness and model
	for _, name := range names {
		if model, ok := models[name]; ok {
			runs[[2]string{model.Harness, model.ID}] = true
		}
	}
	return quality.Answer(rows, compared, costs.price, runs), nil
}

// A measurement is the points of a week one offered model's runs took of a row in a role, on that
// model's provider, and the dollars at listed prices those were.
type measurement struct {
	provider       string
	points, listed float64
}

// A sample is a measurement where its row has board dollars for its role: what it cost, in the
// answer's unit, and its listed dollars, beside those board dollars.
type sample struct {
	role, provider      string
	cost, listed, board float64
}

// A place is a role's row of the lineup, by its release and effort.
type place struct{ role, release, effort string }

// costs are what a lineup's measurements price every role's rows at.
type costs struct {
	// unit is every role's: "board_dollars" before any run of yours measured a row, else "money"
	// once a provider your runs measured has a price a month, else "share", points of a week
	unit      string
	first     map[place]measurement // each measured row's first offered model's
	samples   []sample              // as Python's measured holds them
	providers map[string]string     // each release's first offered model's provider
	makers    map[string]string     // the provider each board's maker names
	prices    map[string]*float64   // each measured provider's price a month, its usual login's
	mean      *float64              // of those prices that are known
	rates     map[string]float64    // what a listed dollar takes of each provider's plans, in the unit
	either    *float64              // the mean of those rates, a provider's with none
}

// measure is the costs of rows at measured: each offered model of names found as one release of
// rows alone measures that release's row at each effort its shares list in each role it did
// there, rated or not, in the order of names, then their efforts, then the roles.  A provider's
// rate is the mean over its plans of each one's week over the listed dollars it holds, as any of
// them may pay for the next task.
func measure(rows []quality.Row, measured *Measures, names []string, models map[string]config.Model) (*costs, error) {
	subs, err := config.Subscriptions()
	if err != nil {
		return nil, err
	}
	c := &costs{unit: "board_dollars", first: map[place]measurement{}, providers: map[string]string{},
		makers: map[string]string{"": ""}, prices: map[string]*float64{}, rates: map[string]float64{}} // no maker names no provider
	shares := measured.Shares
	lineup := map[[2]string]quality.Row{}
	// the lineup's, each under the name the board spells, as lineup matched it, of its last row
	var releases []*boards.Release
	named := map[string]*boards.Release{}
	for _, row := range rows {
		lineup[[2]string{row.Release, row.Effort}] = row
		if named[row.Release] == nil {
			named[row.Release] = &boards.Release{Slug: row.Release}
			releases = append(releases, named[row.Release])
		}
		named[row.Release].Name = row.BoardName
		if _, held := c.makers[row.Maker]; !held {
			if c.makers[row.Maker], err = config.Company(row.Maker); err != nil {
				return nil, err
			}
		}
	}
	index := boards.IndexOf(releases)
	var order []place
	at := map[place][]measurement{}
	for _, name := range names {
		release := ""
		for _, one := range index.Found(models[name].ID) {
			if release != "" && release != one.Release.Slug {
				release = ""
				break
			}
			release = one.Release.Slug
		}
		if release == "" {
			continue
		}
		if _, held := c.providers[release]; !held {
			c.providers[release] = models[name].Provider
		}
		efforts := shares.Dict(name)
		if efforts == nil {
			continue
		}
		for _, effort := range efforts.Keys() {
			// a row naming no effort measured none: ak's runs count only those naming theirs
			did := efforts.Dict(effort)
			if _, listed := lineup[[2]string{release, effort}]; effort == "" || !listed || did == nil {
				continue
			}
			for _, role := range quality.Roles {
				if points, ok := run.Num(did.Get(ConfigRoles[role])); ok {
					here := place{role, release, effort}
					if at[here] == nil {
						order = append(order, here)
					}
					dollars := measured.listed[[3]string{name, effort, ConfigRoles[role]}]
					at[here] = append(at[here], measurement{models[name].Provider, points, dollars})
				}
			}
		}
	}
	if len(order) == 0 {
		return c, nil
	}
	// every provider your runs measured, though no row of the lineup is its measured model
	var known []float64
	for _, name := range names {
		provider := models[name].Provider
		if _, seen := c.prices[provider]; seen || shares.Dict(name) == nil {
			continue
		}
		c.prices[provider] = nil
		for _, sub := range subs {
			if sub.Name == provider {
				if c.prices[provider], err = usage.Price(sub, ""); err != nil {
					return nil, err
				}
			}
		}
		if price := c.prices[provider]; price != nil {
			known = append(known, *price)
		}
	}
	c.unit = "share"
	if len(known) > 0 {
		mean := quality.Sum(known) / float64(len(known))
		c.unit, c.mean = "money", &mean
	}
	var rated []string // the providers with a plan, in the order of their first
	taken := map[string][]float64{}
	for _, one := range measured.plans {
		if taken[one.provider] == nil {
			rated = append(rated, one.provider)
		}
		taken[one.provider] = append(taken[one.provider], c.week(one.price)/one.week)
	}
	var each []float64
	for _, provider := range rated {
		c.rates[provider] = quality.Sum(taken[provider]) / float64(len(taken[provider]))
		each = append(each, c.rates[provider])
	}
	if len(each) > 0 {
		either := quality.Sum(each) / float64(len(each))
		c.either = &either
	}
	for _, here := range order {
		c.first[here] = at[here][0]
		board, ok := lineup[[2]string{here.release, here.effort}].Values.Num(quality.Costs[here.role])
		if !ok || board <= 0 {
			continue
		}
		for _, one := range at[here] {
			c.samples = append(c.samples, sample{here.role, one.provider, c.cost(one.provider, one.points), one.listed, board})
		}
	}
	return c, nil
}

// week is a plan's week in the unit: 12/52 of the month price pays for, else of the mean price,
// else 100 points where no price is known.
func (c *costs) week(price *float64) float64 {
	if c.mean == nil {
		return 100
	}
	if price == nil {
		price = c.mean
	}
	return *price * 12 / 52
}

// cost is what points of provider's week cost in the unit, a point a hundredth of that week.
func (c *costs) cost(provider string, points float64) float64 {
	return c.week(c.prices[provider]) / 100 * points
}

// price is a quality.Pricer: a measured row costs what its first offered model measured, any other
// its board dollars times the cost per board dollar of its role's samples on its provider (its
// release's first offered model's, else the one its board's maker names), else times their
// listed dollars per board dollar at its provider's rate, else at the mean rate; a role no run
// measured, as none measures an orchestrator, takes every role's samples.
func (c *costs) price(role string, _ []quality.Row, rated []*quality.Rating) string {
	if c.unit == "board_dollars" {
		return c.unit // every row as quality.Rated leaves it, at its board's
	}
	var pool []sample
	for _, one := range c.samples {
		if one.role == role {
			pool = append(pool, one)
		}
	}
	if pool == nil {
		pool = c.samples
	}
	for _, row := range rated {
		if mine, ok := c.first[place{role, row.Release, row.Effort}]; ok {
			cost := c.cost(mine.provider, mine.points)
			row.Cost, row.CostRule = &cost, "measured"
			continue
		}
		provider := c.providers[row.Release]
		if provider == "" {
			provider = c.makers[row.Maker]
		}
		var own []sample
		for _, one := range pool {
			if one.provider == provider {
				own = append(own, one)
			}
		}
		var factor *float64 // what a board dollar of its costs
		row.CostRule = "provider"
		if own != nil { // its provider's runs paid a board dollar at what its own plans take
			each := perBoardDollar(own, func(one sample) float64 { return one.cost })
			factor = &each
		} else {
			row.CostRule = "global"
			rate := c.either
			if one, ok := c.rates[provider]; ok {
				rate = &one
			}
			// any other provider's listed dollars take what they take of its plans
			if pool != nil && rate != nil {
				each := perBoardDollar(pool, func(one sample) float64 { return one.listed }) * *rate
				factor = &each
			}
		}
		// Without board dollars or a measured conversion, no same-unit estimate exists.
		row.Cost = nil
		if row.BoardCost != nil && factor != nil {
			cost := *row.BoardCost * *factor
			row.Cost = &cost
		}
	}
	return c.unit
}

// perBoardDollar is what of some, at what of each, a board dollar of theirs took.
func perBoardDollar(some []sample, what func(sample) float64) float64 {
	var took, board []float64
	for _, one := range some {
		took, board = append(took, what(one)), append(board, one.board)
	}
	return quality.Sum(took) / quality.Sum(board)
}
