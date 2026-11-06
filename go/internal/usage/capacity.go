package usage

import (
	"cmp"
	"fmt"
	"maps"
	"math"
	"os"
	"path/filepath"
	"slices"
	"strconv"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/run"
	"agentkit/internal/terminal"
)

// A meter says a percent of its window, and what that window holds in tokens nobody publishes.
// Every worker turn knows both halves: the tokens it spent and how far it moved each weekly meter.
// state/capacity.json keeps those pairs per provider, login and meter, in Python's format under
// Python's lock (usage.PAIRS), and a window holds the sum of their tokens over the sum of the
// percent they moved.
const pairsFile = "capacity.json"

// month is a month of a subscription, in seconds (usage.MONTH).
const month = 365.25 * 86400 / 12

// measuredPairs is capacity.json as it stands, Python's usage._measured: empty where it reads as
// no object.
func measuredPairs() *run.Object {
	data, err := os.ReadFile(filepath.Join(state(), pairsFile))
	if err != nil {
		return run.NewObject()
	}
	value, _ := run.Decode(data)
	return object(value)
}

// wellFormed is the pairs of one meter's list a measure reads, Python's usage._pairs: those whose
// at, tokens, moved and resets_at are numbers.
func wellFormed(value any) []*run.Object {
	var found []*run.Object
	for _, pair := range objects(value) {
		if numbers(pair, "at", "tokens", "moved", "resets_at") {
			found = append(found, pair)
		}
	}
	return found
}

// seen is the ends of the last two windows the snapshot named for that login's meter, Python's
// usage._seen: a window no turn paired still stands between the one after it and older pairs.
func seen(provider, account, meter string) []float64 {
	var ends []float64
	windows := object(object(object(read()).Get("windows")).Get(provider))
	for _, end := range object(windows.Get(cmp.Or(account, config.DefaultAccount))).List(meter) {
		if value, ok := number(end); ok {
			ends = append(ends, value)
		}
	}
	return ends
}

// field is a well-formed pair's number under that key.
func field(pair *run.Object, key string) float64 {
	value, _ := number(pair.Get(key))
	return value
}

// endsOf is the window ends seen and those the pairs name.
func endsOf(seen []float64, pairs []*run.Object) []float64 {
	found := slices.Clone(seen)
	for _, pair := range pairs {
		found = append(found, field(pair, "resets_at"))
	}
	return found
}

// latest is the latest of the ends seen and the pairs', false where there is none.
func latest(seen []float64, pairs []*run.Object) (float64, bool) {
	listed := endsOf(seen, pairs)
	if len(listed) == 0 {
		return 0, false
	}
	return slices.Max(listed), true
}

// recent is the pairs of the window ending at ends and of the window named before it, by a reading
// or by a pair, Python's usage._recent.  That one is the window before only while it ended no
// earlier than this one began, where its length is sized: a reset spent early ends it later, and a
// week nobody read leaves an older one, which counts for nothing.
func recent(pairs []*run.Object, seen []float64, ends, window float64, sized bool) []*run.Object {
	before, named := 0.0, false
	for _, end := range endsOf(seen, pairs) {
		if end < ends && (!sized || end >= ends-window) && (!named || end > before) {
			before, named = end, true
		}
	}
	var kept []*run.Object
	for _, pair := range pairs {
		if at := field(pair, "resets_at"); at == ends || named && at == before {
			kept = append(kept, pair)
		}
	}
	return kept
}

// allocated is how far each pair moved its meter, Python's usage._allocated: each stretch of a
// window's meter that turns claim, from where it stood before them to where they left it, split
// between the turns claiming it by their tokens, as turns overlapping on one login share its move.
// A pair kept before turns noted where they began claims its whole move.
func allocated(pairs []*run.Object) []float64 {
	moved := make([]float64, len(pairs))
	var claims []int
	var windows []float64
	for i, pair := range pairs {
		if _, began := number(pair.Get("prior")); !began {
			moved[i] = field(pair, "moved")
		} else if field(pair, "tokens") > 0 && field(pair, "moved") > 0 {
			claims = append(claims, i)
			if ends := field(pair, "resets_at"); !slices.Contains(windows, ends) {
				windows = append(windows, ends)
			}
		}
	}
	for _, ends := range windows {
		var points []float64
		for _, i := range claims {
			if field(pairs[i], "resets_at") == ends {
				prior := field(pairs[i], "prior")
				points = append(points, prior, prior+field(pairs[i], "moved"))
			}
		}
		slices.Sort(points)
		points = slices.Compact(points)
		for k := 1; k < len(points); k++ {
			left, right := points[k-1], points[k]
			var covering []int
			tokens := 0.0
			for _, i := range claims {
				prior := field(pairs[i], "prior")
				if field(pairs[i], "resets_at") == ends && prior <= left && prior+field(pairs[i], "moved") >= right {
					covering = append(covering, i)
					tokens += field(pairs[i], "tokens")
				}
			}
			for _, i := range covering {
				moved[i] += (right - left) * field(pairs[i], "tokens") / tokens
			}
		}
	}
	return moved
}

// holds is the tokens 100% of that login's meter stands for, nil while none of its pairs moved it,
// and how many pairs it is measured from: those of the window the meter names and the one before
// it, Python's usage.holds.  No meter, or one naming no window, is measured from none.
func holds(provider, account string, meter *run.Object) (any, int) {
	if meter == nil {
		return nil, 0
	}
	name, named := meter.Get("name").(string)
	ends, dated := number(meter.Get("resets_at"))
	if !named || !dated {
		return nil, 0
	}
	window, sized := number(meter.Get("window_secs"))
	listed := object(object(measuredPairs().Get(provider)).Get(cmp.Or(account, config.DefaultAccount))).Get(name)
	pairs := recent(wellFormed(listed), seen(provider, account, name), ends, window, sized)
	moved, tokens := 0.0, 0.0
	for i, each := range allocated(pairs) {
		moved, tokens = moved+each, tokens+field(pairs[i], "tokens")
	}
	if moved <= 0 {
		return nil, len(pairs)
	}
	return run.Number(strconv.FormatFloat(math.RoundToEven(100*tokens/moved), 'f', 0, 64)), len(pairs)
}

// perMillion is what a million tokens cost on a subscription at price a month whose meter's window
// holds tokens, in two significant digits, Python's usage.per_million: nil while unmeasured.
func perMillion(price *float64, tokens any, meter *run.Object) any {
	held, measured := number(tokens)
	if price == nil || !measured || held == 0 {
		return nil
	}
	window, sized := number(meter.Get("window_secs"))
	if !sized || window == 0 {
		window = 7 * 86400
	}
	each, _ := strconv.ParseFloat(strconv.FormatFloat(*price*window/(month*held/1e6), 'g', 2, 64), 64)
	return run.Float(each)
}

// heldText is `week ≈ 310M tokens`, what all of the meter's window holds, in two significant
// digits and an SI letter, Python's usage._held: `-` while unmeasured.  A window that is not a
// week says its length: `30d`.
func heldText(screen terminal.Screen, tokens any, meter *run.Object) string {
	held, measured := number(tokens)
	if !measured {
		return "-"
	}
	shown, _ := strconv.ParseFloat(strconv.FormatFloat(held, 'g', 2, 64), 64)
	letter := ""
	for _, step := range []string{"k", "M", "G", "T"} {
		if shown < 1000 {
			break
		}
		shown, letter = shown/1000, step
	}
	named := "week"
	if window, sized := number(meter.Get("window_secs")); sized && window != 7*86400 {
		named = terminal.FormatAge(window)
	}
	places := 1
	if shown >= 10 {
		places = 0
	}
	return fmt.Sprintf("%s %s %s%s tokens", named, about(screen), strconv.FormatFloat(shown, 'f', places, 64), letter)
}

// buysText is `200 ≈ 0.15 per 1M tokens`, the price a month and what it buys, Python's
// usage._buys: the price alone while the window is unmeasured, `-` without one.
func buysText(screen terminal.Screen, price *float64, tokens any, meter *run.Object) string {
	if price == nil {
		return "-"
	}
	each, measured := number(perMillion(price, tokens, meter))
	if !measured {
		return digits(*price)
	}
	return digits(*price) + " " + about(screen) + " " + digits(each) + " per 1M tokens"
}

// about is the glyph an estimate is said with.
func about(screen terminal.Screen) string {
	if screen.ASCII() {
		return "~"
	}
	return "≈"
}

// digits is a price in plain digits, never an exponent, Python's usage._digits.
func digits(value float64) string {
	return grouped(strconv.FormatFloat(value, 'f', -1, 64))
}

// Rates is, per model the config offers and per effort it runs at or its pairs ran at, the weekly
// percentage points a million of its tokens cost, nil where none of its pairs moved a meter,
// Python's usage.model_rates.  Every login of a provider pools its pairs by tokens, each login's
// meter moves allocated on their own; a meter a model claims as its own cap is not its
// provider's week, and only the shared week the snapshot reads is measured where it reads one.
// Nobody is asked.
func (r *Readings) Rates() (*run.Object, error) {
	names, err := config.Offered()
	if err != nil {
		return nil, err
	}
	type total struct{ tokens, moved float64 }
	totals := map[[2]string]*total{}
	measured := measuredPairs()
	for _, provider := range measured.Keys() {
		scoped := map[string]bool{}
		for _, name := range names {
			if model := r.models[name]; model.Provider == provider && model.Meter != "" {
				scoped[model.Meter] = true
			}
		}
		listed, err := config.Accounts(provider)
		if err != nil {
			return nil, err
		}
		logins := object(measured.Get(provider))
		for _, account := range logins.Keys() {
			prov := object(r.providers.Get(provider))
			if account != config.DefaultAccount || len(listed) > 0 {
				prov = object(object(prov.Get("accounts")).Get(account))
			}
			shared := r.sharedWeek(provider, prov)
			meters := object(logins.Get(account))
			for _, name := range meters.Keys() {
				if scoped[name] || shared != nil && name != shared.Str("name") {
					continue
				}
				pairs, ends := wellFormed(meters.Get(name)), seen(provider, account, name)
				end, dated, window, sized := 0.0, false, 0.0, false
				if shared != nil {
					end, dated = number(shared.Get("resets_at"))
					dated = dated && end != 0
					window, sized = number(shared.Get("window_secs"))
				}
				if !dated {
					end, dated = latest(ends, pairs)
				}
				if !dated {
					continue
				}
				pairs = recent(pairs, ends, end, window, sized)
				for i, moved := range allocated(pairs) {
					model, _ := pairs[i].Get("model").(string)
					effort, said := pairs[i].Get("effort").(string)
					if !said || !slices.Contains(names, model) || r.models[model].Provider != provider {
						continue
					}
					key := [2]string{model, effort}
					if totals[key] == nil {
						totals[key] = &total{}
					}
					totals[key].tokens += field(pairs[i], "tokens")
					totals[key].moved += moved
				}
			}
		}
	}
	found := run.NewObject()
	for _, name := range names {
		model := r.models[name]
		efforts := map[string]bool{}
		for _, key := range config.RoleEfforts {
			effort, set := model.Efforts[key]
			if !set {
				effort = model.Efforts["effort"]
			}
			efforts[effort] = true
		}
		for key := range totals {
			if key[0] == name {
				efforts[key[1]] = true
			}
		}
		rates := run.NewObject()
		for _, effort := range slices.Sorted(maps.Keys(efforts)) {
			rates.Set(effort, nil)
			if spent := totals[[2]string{name, effort}]; spent != nil && spent.tokens > 0 && spent.moved > 0 {
				rates.Set(effort, 1e6*spent.moved/spent.tokens)
			}
		}
		found.Set(name, rates)
	}
	return found, nil
}

// A paired meter is a meter as the reading after a turn holds it and the pair it made.
type paired struct{ meter, pair *run.Object }

// keepPairs adds one turn's pairs to capacity.json, written whole under its lock, Python's
// usage._keep_pairs: each meter keeps its latest window and the one before it, the latest being
// the latest any reading or pair named, as a turn recording late must not drop a later window's.
func keepPairs(src source, read []paired) error {
	path := filepath.Join(state(), pairsFile)
	beside := strings.TrimSuffix(path, filepath.Ext(path)) // Python's path.with_suffix
	held, err := lockFile(beside + ".lock")
	if err != nil {
		return err
	}
	defer held.Close()
	blob := measuredPairs()
	logins := object(blob.Get(src.Name))
	blob.Set(src.Name, logins)
	key := cmp.Or(src.account, config.DefaultAccount)
	meters := object(logins.Get(key))
	logins.Set(key, meters)
	for _, each := range read {
		name := each.meter.Str("name")
		kept := append(wellFormed(meters.Get(name)), each.pair)
		ends := seen(src.Name, src.account, name)
		end, _ := latest(ends, kept)
		window, sized := number(each.meter.Get("window_secs"))
		meters.Set(name, list(recent(kept, ends, end, window, sized)))
	}
	tmp := fmt.Sprintf("%s.tmp-%d-%d", beside, os.Getpid(), writes.Add(1)-1)
	defer os.Remove(tmp)
	if err := os.WriteFile(tmp, []byte(run.Line(blob)), 0o666); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}
