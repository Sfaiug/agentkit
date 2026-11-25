package matrix

import (
	"cmp"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"sync"
	"time"

	"agentkit/internal/boards"
	"agentkit/internal/config"
	"agentkit/internal/history"
	"agentkit/internal/logins"
	"agentkit/internal/quality"
	"agentkit/internal/run"
	"agentkit/internal/usage"
)

// What a login spent at listed prices, Python's spend module: each token ak keeps by login, model
// and type, a seat's in seat_usage and a worker turn's in turn_usage, priced at its model's listed
// price for its type.  Priced per type, a login's spend foretold its subscription's next meter
// readings within 2-8%, where raw token sums were 23% to 75% off (the owner's back-test, 6 Nov
// 2026).

const (
	drift     = 600       // a reading is of the week of the one before it, by resets_at, at most this many seconds later
	SpentOver = 7 * 86400 // what a login's spend is priced over, and its plan's week fitted
)

// counts are the types of token a row keeps.
const counts = "input, cache_write, cache_read, output"

// A spend reads one history at the listed prices of one set of boards.
type spend struct {
	db     *history.DB
	index  boards.Index
	prices map[string][]float64 // by model, nil where it lists none
	ours   map[[2]string]bool   // whether a harness runs models of a provider alone
}

// spending is a spend of history.db, through a connection that cannot write, at held's prices.
func spending(held *run.Object) *spend {
	return &spend{db: history.Look(), index: boards.IndexOf(boards.Current(held)), prices: map[string][]float64{}, ours: map[[2]string]bool{}}
}

// A spent row is one of a login's rows: its harness ("" where unknown), model, tokens and counts,
// known false where one is, and the dollars a turn row kept (history's listed_usd), saved false
// where it kept none.
type spent struct {
	harness, model string
	tokens         float64
	counts         []float64
	known          bool
	kept           float64
	saved          bool
}

// measures is Python's spend.roles: of each offered model at each effort it did a worker role at,
// the means over the task runs that ended where it did of the dollars the role's turn_usage rows
// took (dollars), and of the points of a week that is, each row's dollars times 100 over the week
// of its login under the model's provider (plans); and each login's plan where its week holds some.  A run's reviewer is at the one effort its reviews name; a run counts for
// nothing in a role a counted turn of which kept no row, a row of which has no listed price or a
// login of which has no week.
func measures(held *run.Object) (*Measures, error) {
	names, err := config.Offered()
	if err != nil {
		return nil, err
	}
	models, err := config.Models()
	if err != nil {
		return nil, err
	}
	readings, err := usage.Cached()
	if err != nil {
		return nil, err
	}
	subs, err := config.Subscriptions()
	if err != nil {
		return nil, err
	}
	var accounts []usage.Week
	for _, login := range readings.Weeks() {
		if slices.ContainsFunc(subs, func(sub config.Subscription) bool { return sub.Name == login.Provider }) {
			accounts = append(accounts, login)
		}
	}
	s := spending(held)
	defer s.db.Close()
	found := &Measures{Shares: run.NewObject(), listed: map[[3]string]float64{}}
	weeks := map[[2]string]float64{} // by provider and the account its rows name
	now := float64(time.Now().UnixNano()) / 1e9
	fits := s.plans(accounts, [2]float64{now - SpentOver, now})[0]
	for _, login := range accounts {
		week, known := fits[login].Week()
		if !known {
			continue
		}
		account := cmp.Or(login.Account, config.DefaultAccount)
		weeks[[2]string{login.Provider, account}] = week
		// one its subscription no longer lists is signed out: the usage cache keeps it until it
		// next refreshes, and its week still prices the runs it did, but it pays for no next task
		listed, err := config.Accounts(login.Provider)
		if err != nil {
			return nil, err
		}
		if week == 0 || len(listed) > 0 && !slices.Contains(listed, account) {
			continue
		}
		sub := subs[slices.IndexFunc(subs, func(sub config.Subscription) bool { return sub.Name == login.Provider })]
		price, err := usage.Price(sub, login.Account)
		if err != nil {
			return nil, err
		}
		found.plans = append(found.plans, plan{login.Provider, price, week})
	}
	type task struct{ run, role string }
	type did struct {
		name, effort string
		said         bool // whether it names an effort
		turns        map[string]bool
	}
	type kept struct {
		turn, account string
		spent
	}
	var tasks []task
	dids := map[task]*did{}
	rows := map[task][]kept{}
	// each role's model and effort, by their columns
	who := map[string][2]string{"executor": {"executor", "executor_effort"}, "reviewer": {"reviewer", "reviewed"}}
	// one read, as a run resumed between two would add its new turns' rows to its ended sample
	for _, row := range s.db.Select("SELECT run_id, executor, executor_effort, reviewer, (SELECT CASE WHEN " +
		"COUNT(DISTINCT effort) = 1 THEN MIN(effort) END FROM reviews WHERE reviews.run_id = runs.run_id) AS reviewed, " +
		"counted_turns, turn, role, account, model, listed_usd, " + counts + " FROM runs LEFT JOIN " + s.db.Migrated("turn_usage") +
		" USING (run_id) WHERE kind = 'task' AND finished_at IS NOT NULL") {
		if row["turn"] != nil {
			key := task{row.Text("run_id"), row.Text("role")}
			rows[key] = append(rows[key], kept{row.Text("turn"), row.Text("account"), counted(row, "", 0)})
		}
		named, _ := run.Decode([]byte(cmp.Or(row.Text("counted_turns"), "[]")))
		turns, _ := named.([]any)
		for _, each := range turns {
			turn, _ := each.(string)
			role := "executor"
			if strings.HasPrefix(filepath.Base(turn), "reviewer") {
				role = "reviewer"
			}
			key := task{row.Text("run_id"), role}
			if dids[key] == nil {
				tasks = append(tasks, key)
				dids[key] = &did{row.Text(who[role][0]), row.Text(who[role][1]), row[who[role][1]] != nil, map[string]bool{}}
			}
			dids[key].turns[turn] = true
		}
	}
	type sample struct{ name, effort, role string }
	var order []sample
	samples := map[sample][][2]float64{} // each run's points and dollars
	for _, key := range tasks {
		d, kept := dids[key], rows[key]
		for _, row := range kept {
			delete(d.turns, row.turn)
		}
		if !slices.Contains(names, d.name) || !d.said || len(d.turns) > 0 {
			continue
		}
		var points, costs []float64
		for _, row := range kept {
			cost, priced := s.dollars(row.spent)
			week, held := weeks[[2]string{models[d.name].Provider, row.account}]
			if priced && held {
				points, costs = append(points, 100*cost/week), append(costs, cost)
			}
		}
		if len(points) == len(kept) {
			each := sample{d.name, d.effort, key.role}
			if samples[each] == nil {
				order = append(order, each)
			}
			samples[each] = append(samples[each], [2]float64{quality.Sum(points), quality.Sum(costs)})
		}
	}
	for _, each := range order {
		if found.Shares.Dict(each.name) == nil {
			found.Shares.Set(each.name, run.NewObject())
		}
		efforts := found.Shares.Dict(each.name)
		if efforts.Dict(each.effort) == nil {
			efforts.Set(each.effort, run.NewObject())
		}
		var points, costs []float64
		for _, one := range samples[each] {
			points, costs = append(points, one[0]), append(costs, one[1])
		}
		runs := float64(len(samples[each]))
		efforts.Dict(each.effort).Set(each.role, quality.Sum(points)/runs)
		found.listed[[3]string{each.name, each.effort, each.role}] = quality.Sum(costs) / runs
	}
	return found, nil
}

// plans is each login's Plan over each of windows, (since, until) each, Python's spend.weeks: per
// provider, a plan's points and dollars are summed over every login's probe readings of its shared
// week in the window, a model's own cap of its name (scope) none, a reading kept with no plan its
// login's plan now.  A login's readings of one plan and one week, by drift, are cut at each turn of
// unknown tokens (stretches), read once from the earliest window, as a turn that ended before a
// window's first reading cuts nothing in it: read for each of Checks's fourteen, they took the
// owner 9.4 s.  Each stretch rose from its earliest reading to its highest, what the login spent
// (listed) from the earliest to the first at the highest bought that rise, and one whose spend
// cannot be priced counts for nothing.
func (s *spend) plans(accounts []usage.Week, windows ...[2]float64) []map[usage.Week]usage.Plan {
	type key struct {
		window                  int
		provider, account, plan string
	}
	type group struct {
		key
		start float64
	}
	plans := map[usage.Week]string{} // each login's plan now, none where logins.json knows none
	for _, login := range accounts {
		if kept := logins.Of(login.Provider, login.Account); kept != nil {
			plans[login] = kept.Str("plan")
		}
	}
	var order []group
	groups := map[group][][2]float64{}
	start, last := map[key]float64{}, map[key]float64{}
	for window, span := range windows {
		for _, login := range accounts {
			if login.Meter == "" {
				continue
			}
			for _, row := range s.db.Select("SELECT used, resets_at, at, plan FROM "+s.db.Migrated("meter_readings")+
				" WHERE provider = ? AND account = ? AND meter = ? AND scope IS NULL AND source = 'probe' AND at >= ? AND at <= ? AND "+
				"typeof(used) IN ('integer', 'real') AND typeof(resets_at) IN ('integer', 'real') ORDER BY resets_at",
				login.Provider, cmp.Or(login.Account, config.DefaultAccount), login.Meter, span[0], span[1]) {
				used, _ := row.Num("used")
				resets, _ := row.Num("resets_at")
				at, _ := row.Num("at")
				k := key{window, login.Provider, login.Account, cmp.Or(row.Text("plan"), plans[login])}
				if before, seen := last[k]; !seen || resets-before > drift {
					start[k] = resets
				}
				last[k] = resets
				each := group{k, start[k]}
				if groups[each] == nil {
					order = append(order, each)
				}
				groups[each] = append(groups[each], [2]float64{at, used})
			}
		}
	}
	unknown := s.db.Unknowns(slices.MinFunc(windows, func(a, b [2]float64) int { return cmp.Compare(a[0], b[0]) })[0])
	type fit struct {
		window         int
		provider, plan string
	}
	fits := map[fit]usage.Plan{}
	for _, each := range order {
		for _, stretch := range s.stretches(each.provider, each.account, groups[each], unknown) {
			began, top, until := stretch[0], stretch[0][1], stretch[0][0]
			for _, reading := range stretch[1:] {
				if reading[1] > top {
					top, until = reading[1], reading[0]
				}
			}
			if dollars, priced := s.listed(each.provider, each.account, began[0], until); priced {
				at := fit{each.window, each.provider, each.plan}
				plan := fits[at]
				plan.Points, plan.Dollars = plan.Points+top-began[1], plan.Dollars+dollars
				fits[at] = plan
			}
		}
	}
	found := make([]map[usage.Week]usage.Plan, len(windows))
	for window := range windows {
		found[window] = map[usage.Week]usage.Plan{}
		for _, login := range accounts {
			plan := fits[fit{window, login.Provider, plans[login]}]
			plan.Name = plans[login]
			found[window][login] = plan
		}
	}
	return found
}

// listed is the dollars the login of provider spent between since and until at listed prices,
// false where none of its rows from then can be priced, Python's spend.listed.  A row is the
// login's where its account is and its harness runs models of that provider alone; a row it
// cannot price, its model listing no price, its counts unknown or its cost no float's, costs what
// the login's priced rows cost a token.  A turn row costs the dollars it kept, whatever the boards
// list now.
func (s *spend) listed(provider, account string, since, until float64) (float64, bool) {
	dollars, priced, unpriced, found := 0.0, 0.0, 0.0, false
	for _, row := range s.rows(cmp.Or(account, config.DefaultAccount), since, until) {
		if !s.runsAlone(row.harness, provider) {
			continue
		}
		cost, known := s.dollars(row)
		if !known {
			unpriced += row.tokens
			continue
		}
		found = true
		dollars += cost
		priced += row.tokens
	}
	if !found {
		return 0, false
	}
	if priced == 0 {
		return dollars, true
	}
	// the tokens' ratio first: dollars near a float's largest times tokens overflow where the
	// estimate does not
	return dollars + dollars*(unpriced/priced), true
}

// rows are the login's rows between since and until, Python's spend._rows: a seat row at its at, a
// turn row the share of its span, from its began to its at, that falls between them, one with no
// began at its at.  A seat row's harness is its event's text before the first `:`, a turn row's
// the one its turn's harness receipt names; a seat row's tokens are its own, a turn row's its
// counts summed; a seat row keeps no dollars, a turn row its share of those it kept, if any.
func (s *spend) rows(account string, since, until float64) []spent {
	var found []spent
	for _, row := range s.db.Select("SELECT event, model, tokens, "+counts+" FROM seat_usage "+
		"WHERE account = ? AND at >= ? AND at <= ?", account, since, until) {
		tokens, _ := row.Num("tokens")
		harness, _, _ := strings.Cut(row.Text("event"), ":")
		found = append(found, counted(row, harness, tokens))
	}
	for _, row := range s.db.Select("SELECT turn, model, COALESCE(began, at) AS began, at, listed_usd, "+counts+
		" FROM "+s.db.Migrated("turn_usage")+" WHERE account = ? AND at >= ? AND COALESCE(began, at) <= ?", account, since, until) {
		began, _ := row.Num("began")
		at, _ := row.Num("at")
		share := 1.0
		if at > began {
			share = (min(at, until) - max(began, since)) / (at - began)
		}
		if share == 0 { // it only touches the time at an end: none of it was spent then
			continue
		}
		each := counted(row, harnessOf(row.Text("turn")), 0)
		for i := range each.counts {
			each.counts[i] *= share
		}
		each.tokens, each.kept = quality.Sum(each.counts), each.kept*share
		found = append(found, each)
	}
	return found
}

// harnessOf is the harness receipt of a turn that kept a turn_usage row, "" for none, read once in
// a process, Python's spend._harness: a row is written once its turn has ended, and the receipt
// changes no more after that.  Read for each of its rows in each provider's pricing, they took the
// owner 5.9 s of an `ak usage`.
func harnessOf(turn string) string {
	if turn == "" {
		return ""
	}
	once, _ := harnesses.LoadOrStore(turn, sync.OnceValue(func() string {
		receipt, _ := os.ReadFile(filepath.Join(turn, "harness"))
		return strings.TrimSpace(string(receipt))
	}))
	return once.(func() string)()
}

var harnesses sync.Map

// counted is the row's model, counts and the dollars it kept, an unknown count counting 0 toward
// its tokens.
func counted(row history.Row, harness string, tokens float64) spent {
	each := spent{harness: harness, model: row.Text("model"), tokens: tokens, known: true}
	each.kept, each.saved = row.Num("listed_usd")
	for _, column := range strings.Split(counts, ", ") {
		count, ok := row.Num(column)
		each.counts, each.known = append(each.counts, count), each.known && ok
	}
	return each
}

// runsAlone is whether the config runs models of provider alone on harness, as a login's spend
// counts only such a harness's rows.
func (s *spend) runsAlone(harness, provider string) bool {
	key := [2]string{harness, provider}
	if alone, asked := s.ours[key]; asked {
		return alone
	}
	s.ours[key] = slices.Equal(config.HarnessProviders(harness), []string{provider})
	return s.ours[key]
}

// dollars is what a row cost, Python's spend._cost: those it kept, else what its counts cost at
// its model's listed prices now (boards.Dollars), false where either is unknown.
func (s *spend) dollars(row spent) (float64, bool) {
	if row.saved {
		return row.kept, true
	}
	if !row.known {
		return 0, false
	}
	prices, asked := s.prices[row.model]
	if !asked {
		prices = s.index.Prices(row.model)
		s.prices[row.model] = prices
	}
	return boards.Dollars(prices, row.counts)
}
