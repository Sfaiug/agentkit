package matrix

import (
	"cmp"
	"os"
	"path/filepath"
	"slices"
	"strings"
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

// counts are the types of token a row keeps, and listed the column of a release's values listing
// its price a million tokens of each.
const counts = "input, cache_write, cache_read, output"

var listed = []string{"aa.price1mInputTokens", "aa.cacheWritePrice", "aa.cacheHitPrice", "aa.price1mOutputTokens"}

// A spend reads one history at the listed prices of one set of boards.
type spend struct {
	db     *history.DB
	index  map[string][]hit
	prices map[string][]float64 // by model, nil where it lists none
	ours   map[[2]string]bool   // whether a harness runs models of a provider alone
}

// spending is a spend of history.db, through a connection that cannot write, at held's prices.
func spending(held *run.Object) *spend {
	return &spend{db: history.Look(), index: indexOf(boards.Current(held)), prices: map[string][]float64{}, ours: map[[2]string]bool{}}
}

// A spent row is one of a login's rows: its harness ("" where unknown), model, tokens and counts,
// known false where one is.
type spent struct {
	harness, model string
	tokens         float64
	counts         []float64
	known          bool
}

// shares is {model: {effort: {role: share}}}, Python's spend.roles: of each offered model at each
// effort it did a worker role at, the mean over the task runs that ended where it did of the
// points of a week the role's turn_usage rows took, at held's listed prices times 100 over the
// week of each row's login under the model's provider (plans).  A run's reviewer is at the one
// effort its reviews name; a run counts for nothing in a role a counted turn of which kept no row,
// a row of which has no listed price or a login of which has no week.
func shares(held *run.Object) (*run.Object, error) {
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
	weeks := map[[2]string]float64{} // by provider and the account its rows name
	for login, plan := range s.plans(accounts, float64(time.Now().UnixNano())/1e9, SpentOver) {
		if week, known := plan.Week(); known {
			weeks[[2]string{login.Provider, cmp.Or(login.Account, config.DefaultAccount)}] = week
		}
	}
	type task struct{ run, role string }
	type did struct {
		name, effort string
		said         bool // whether it names an effort
		turns        map[string]bool
	}
	var tasks []task
	dids := map[task]*did{}
	// each role's model and effort, by their columns
	who := map[string][2]string{"executor": {"executor", "executor_effort"}, "reviewer": {"reviewer", "reviewed"}}
	for _, row := range s.db.Select("SELECT run_id, executor, executor_effort, reviewer, (SELECT CASE WHEN " +
		"COUNT(DISTINCT effort) = 1 THEN MIN(effort) END FROM reviews WHERE reviews.run_id = runs.run_id) AS reviewed, " +
		"counted_turns FROM runs WHERE kind = 'task' AND finished_at IS NOT NULL") {
		counted, _ := run.Decode([]byte(cmp.Or(row.Text("counted_turns"), "[]")))
		turns, _ := counted.([]any)
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
	type kept struct {
		turn, account string
		spent
	}
	rows := map[task][]kept{}
	for _, row := range s.db.Select("SELECT run_id, turn, role, account, model, " + counts + " FROM turn_usage") {
		key := task{row.Text("run_id"), row.Text("role")}
		rows[key] = append(rows[key], kept{row.Text("turn"), row.Text("account"), counted(row, "", 0)})
	}
	type sample struct{ name, effort, role string }
	var order []sample
	samples := map[sample][]float64{}
	for _, key := range tasks {
		d, kept := dids[key], rows[key]
		for _, row := range kept {
			delete(d.turns, row.turn)
		}
		if !slices.Contains(names, d.name) || !d.said || len(d.turns) > 0 {
			continue
		}
		var points []float64
		for _, row := range kept {
			dollars, priced := s.dollars(row.spent)
			week, held := weeks[[2]string{models[d.name].Provider, row.account}]
			if priced && held {
				points = append(points, 100*dollars/week)
			}
		}
		if len(points) == len(kept) {
			each := sample{d.name, d.effort, key.role}
			if samples[each] == nil {
				order = append(order, each)
			}
			samples[each] = append(samples[each], quality.Sum(points))
		}
	}
	found := run.NewObject()
	for _, each := range order {
		if found.Dict(each.name) == nil {
			found.Set(each.name, run.NewObject())
		}
		efforts := found.Dict(each.name)
		if efforts.Dict(each.effort) == nil {
			efforts.Set(each.effort, run.NewObject())
		}
		efforts.Dict(each.effort).Set(each.role, quality.Sum(samples[each])/float64(len(samples[each])))
	}
	return found, nil
}

// plans is each login's Plan, Python's usage.plan_weeks over spend.weeks: per provider, a plan's
// points and dollars are summed over every login's probe readings of its shared week over the over
// seconds up to now, a reading kept with no plan its login's plan now.  A login's readings of one
// plan and one week, by drift, rose from the earliest to the highest; what the login spent
// (listed) from the earliest to the first at the highest bought that rise, and one whose spend
// cannot be priced counts for nothing.
func (s *spend) plans(accounts []usage.Week, now, over float64) map[usage.Week]usage.Plan {
	type key struct{ provider, account, plan string }
	type group struct {
		key
		start float64
	}
	plans := map[usage.Week]string{} // each login's plan now, none where logins.json knows none
	var order []group
	groups := map[group][][2]float64{}
	start, last := map[key]float64{}, map[key]float64{}
	for _, login := range accounts {
		if kept := logins.Of(login.Provider, login.Account); kept != nil {
			plans[login] = kept.Str("plan")
		}
		if login.Meter == "" {
			continue
		}
		for _, row := range s.db.Select("SELECT used, resets_at, at, plan FROM meter_readings WHERE provider = ? AND "+
			"account = ? AND meter = ? AND source = 'probe' AND at >= ? AND at <= ? AND "+
			"used IS NOT NULL AND resets_at IS NOT NULL ORDER BY resets_at",
			login.Provider, cmp.Or(login.Account, config.DefaultAccount), login.Meter, now-over, now) {
			used, _ := row.Num("used")
			resets, _ := row.Num("resets_at")
			at, _ := row.Num("at")
			k := key{login.Provider, login.Account, cmp.Or(row.Text("plan"), plans[login])}
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
	fits := map[[2]string]usage.Plan{} // by provider and plan
	for _, each := range order {
		readings := groups[each]
		began := slices.MinFunc(readings, func(a, b [2]float64) int { return cmp.Or(cmp.Compare(a[0], b[0]), cmp.Compare(a[1], b[1])) })
		top, until := readings[0][1], readings[0][0]
		for _, reading := range readings[1:] {
			if reading[1] > top {
				top, until = reading[1], reading[0]
			} else if reading[1] == top {
				until = min(until, reading[0])
			}
		}
		if dollars, priced := s.listed(each.provider, each.account, began[0], until); priced {
			fit := fits[[2]string{each.provider, each.plan}]
			fit.Points, fit.Dollars = fit.Points+top-began[1], fit.Dollars+dollars
			fits[[2]string{each.provider, each.plan}] = fit
		}
	}
	found := map[usage.Week]usage.Plan{}
	for _, login := range accounts {
		fit := fits[[2]string{login.Provider, plans[login]}]
		fit.Name = plans[login]
		found[login] = fit
	}
	return found
}

// listed is the dollars the login of provider spent between since and until at listed prices,
// false where none of its rows from then can be priced, Python's spend.listed.  A row is the
// login's where its account is and its harness runs models of that provider alone; a row it
// cannot price, its model listing no price or its counts unknown, costs what the login's priced
// rows cost a token.
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
	return dollars + unpriced*dollars/priced, true
}

// rows are the login's rows between since and until, Python's spend._rows: a seat row at its at, a
// turn row the share of its span, from its began to its at, that falls between them, one with no
// began at its at.  A seat row's harness is its event's text before the first `:`, a turn row's
// the one its turn's harness receipt names; a seat row's tokens are its own, a turn row's its
// counts summed.
func (s *spend) rows(account string, since, until float64) []spent {
	var found []spent
	for _, row := range s.db.Select("SELECT event, model, tokens, "+counts+" FROM seat_usage "+
		"WHERE account = ? AND at >= ? AND at <= ?", account, since, until) {
		tokens, _ := row.Num("tokens")
		harness, _, _ := strings.Cut(row.Text("event"), ":")
		found = append(found, counted(row, harness, tokens))
	}
	for _, row := range s.db.Select("SELECT turn, model, COALESCE(began, at) AS began, at, "+counts+" FROM turn_usage "+
		"WHERE account = ? AND at >= ? AND COALESCE(began, at) <= ?", account, since, until) {
		began, _ := row.Num("began")
		at, _ := row.Num("at")
		share := 1.0
		if at > began {
			share = (min(at, until) - max(began, since)) / (at - began)
		}
		if share == 0 { // it only touches the time at an end: none of it was spent then
			continue
		}
		harness := ""
		if turn := row.Text("turn"); turn != "" {
			receipt, _ := os.ReadFile(filepath.Join(turn, "harness"))
			harness = strings.TrimSpace(string(receipt))
		}
		each := counted(row, harness, 0)
		for i := range each.counts {
			each.counts[i] *= share
		}
		each.tokens = quality.Sum(each.counts)
		found = append(found, each)
	}
	return found
}

// counted is the row's model and counts, an unknown count counting 0 toward its tokens.
func counted(row history.Row, harness string, tokens float64) spent {
	each := spent{harness: harness, model: row.Text("model"), tokens: tokens, known: true}
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

// dollars is what a row's counts cost at its model's listed prices, a million tokens of each,
// false where either is unknown, Python's spend._dollars.
func (s *spend) dollars(row spent) (float64, bool) {
	prices := s.listedPrices(row.model)
	if prices == nil || !row.known {
		return 0, false
	}
	costs := make([]float64, len(prices))
	for i, price := range prices {
		costs[i] = row.counts[i] * price
	}
	return quality.Sum(costs) / 1e6, true
}

// listedPrices is a model's listed price a million tokens of each type, nil where it has none,
// Python's spend._prices: its release's, the one found finds alone, at the release's default
// effort, else its first; a cache price it lists none of is its input price, and one listing no
// input or output price has none.
func (s *spend) listedPrices(model string) []float64 {
	if prices, asked := s.prices[model]; asked {
		return prices
	}
	s.prices[model] = nil
	if model == "" {
		return nil
	}
	var release *boards.Release
	for _, one := range found(s.index, model) {
		if release != nil && release.Slug != one.release.Slug {
			return nil
		}
		release = one.release
	}
	if release == nil || len(release.Efforts) == 0 {
		return nil
	}
	values := release.Efforts[max(0, slices.IndexFunc(release.Efforts, func(effort *boards.Effort) bool { return effort.Default }))].Values
	fresh, priced := values.Num(listed[0])
	if !priced || !values.Has(listed[len(listed)-1]) {
		return nil
	}
	prices := make([]float64, len(listed))
	for i, column := range listed {
		prices[i] = fresh
		if price, ok := values.Num(column); ok {
			prices[i] = price
		}
	}
	s.prices[model] = prices
	return prices
}
