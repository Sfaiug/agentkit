package usage

import (
	"math"
	"math/big"
	"strconv"
	"strings"
	"unicode"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

const (
	sessionSecs = 18000.0    // the 5h rolling window every harness reports as its session meter
	trustedFor  = 6 * 3600.0 // seconds a reading no probe could refresh still ranks
)

// gateFlags stamps each record with what is derived from its meters on every read, never kept
// as a verdict, Python's usage._gate_flags: each meter spent at 100% used, the record spent, on
// credits, its gap, pace, headroom and budget, and a refusal's mark dropped once it has passed.
func gateFlags(providers *run.Object, now float64, models map[string]config.Model) *run.Object {
	for _, name := range providers.Keys() {
		prov, ok := providers.Get(name).(*run.Object)
		if !ok {
			continue
		}
		until, marked := number(prov.Get("exhausted_until"))
		if !marked || until <= now || freshWindow(prov, prov, now) {
			for _, key := range mark {
				prov.Delete(key)
			}
			marked = false
		}
		spent := false
		for _, meter := range objects(prov.Get("meters")) {
			at, dated := run.Num(meter.Get("resets_at"))
			meter.Set("reset_at", nil)
			if reset, ok := number(meter.Get("resets_at")); ok {
				meter.Set("reset_at", reset)
			}
			meter.Set("tier_a_exhausted", used(meter) >= 100 && dated && at > now)
			meter.Set("exhausted", used(meter) >= 100)
			spent = spent || used(meter) >= 100
		}
		onCredits := spent && creditsLeft(prov) > 0
		prov.Set("on_credits", onCredits)
		prov.Set("exhausted", marked || spent && !onCredits)
		week, own := splitWeek(name, prov, models)
		prov.Delete("effective_used")
		prov.Delete("gap")
		if week != nil {
			prov.Set("gap", minus(week.Get("used"), own.Get("used")))
		}
		prov.Set("pace", topPace(prov.List("meters")))
		prov.Set("headroom", nil)
		if room, ok := headroom(weekly(prov)); ok {
			prov.Set("headroom", room)
		}
		budget, why := providerBudget(prov, now)
		prov.Set("budget_reason", nil)
		if why != "" {
			prov.Set("budget_reason", why)
		}
		prov.Set("budget", round(budget, 3))
	}
	return providers
}

// splitWeek is the shared week and the one model's own cap, where config.toml and both meters
// describe that split, Python's usage._split_week; nil where they do not.
func splitWeek(provider string, prov *run.Object, models map[string]config.Model) (week, own *run.Object) {
	scoped, claims, unclaimed := "", 0, false
	for _, model := range models {
		if model.Provider == provider && model.Meter == "" {
			unclaimed = true
		} else if model.Provider == provider && model.Meter != scoped {
			scoped, claims = model.Meter, claims+1
		}
	}
	if claims != 1 || !unclaimed {
		return nil, nil
	}
	byName := map[string]*run.Object{}
	for _, meter := range objects(prov.Get("meters")) {
		if !session(meter) {
			byName[meter.Str("name")] = meter
		}
	}
	week, own = byName["weekly_all"], byName[scoped]
	if week == nil || own == nil || scoped == "weekly_all" {
		return nil, nil
	}
	return week, own
}

// providerBudget is a reading's smallest budget among its weekly meters, unknown before any known
// one, and why it is unknown, "" where it is known, Python's usage.provider_budget.
func providerBudget(prov *run.Object, now float64) (float64, string) {
	if prov.Truthy("none") && !prov.Truthy("error") {
		return 1, "" // meterless but answering: neutral
	}
	best, why, found := 0.0, "", false
	for _, meter := range objects(prov.Get("meters")) {
		if session(meter) {
			continue
		}
		budget, reason := windowBudget(prov, meter, now)
		if !found || reason != "" && why == "" || (reason == "") == (why == "") && budget < best {
			best, why, found = budget, reason, true
		}
	}
	if !found {
		return windowBudget(prov, nil, now)
	}
	return best, why
}

// windowBudget is what is left of a weekly meter over the part of its window still to go, and
// why there is none to tell, Python's usage._budget.
func windowBudget(prov, week *run.Object, now float64) (float64, string) {
	if prov.Truthy("error") {
		return 0, text(prov.Get("error"))
	}
	since, dated := number(prov.Get("stale_since"))
	if prov.Truthy("probe_error") && (!dated || !(now-since >= 0 && now-since <= trustedFor)) {
		return 0, text(prov.Get("probe_error"))
	}
	if week == nil || !numbers(week, "used") {
		return 0, "no weekly meter reported"
	}
	spent, _ := number(week.Get("used"))
	resets, dated := number(week.Get("resets_at"))
	window, long := number(week.Get("window_secs"))
	if !dated || !long || resets <= 0 || window <= 0 {
		return 0, "gate meter has no valid reset time or window length"
	}
	left := max(0, min(1, (100-spent)/100))
	remaining := max(0, min(1, (resets-now)/window))
	if remaining == 0 {
		return 0, "gate window has reset; awaiting fresh meters"
	}
	return left / remaining, ""
}

// weekly is a reading's tightest weekly meter, the session aside, nil where it has none.
func weekly(prov *run.Object) *run.Object {
	var worst *run.Object
	for _, meter := range objects(prov.Get("meters")) {
		if !session(meter) && (worst == nil || used(meter) > used(worst)) {
			worst = meter
		}
	}
	return worst
}

// withoutPast is a record minus every meter whose window has rolled over, its pace derived again
// and an error where nothing is left, Python's usage._without_past.
func withoutPast(prov *run.Object, now float64, name string) *run.Object {
	meters := []any{}
	for _, each := range prov.List("meters") {
		if meter, ok := each.(*run.Object); !ok || !past(meter, now) {
			meters = append(meters, each)
		}
	}
	out := prov.Copy()
	out.Set("meters", meters)
	out.Set("pace", topPace(meters))
	if prov.Truthy("none") && !prov.Truthy("error") {
		return out
	}
	switch {
	case len(meters) > 0 || prov.Truthy("error"):
		out.Set("error", prov.Get("error"))
	case prov.Truthy("meters"):
		out.Set("error", "unknown: every meter "+name+" reports has already reset")
	default: // its reading gone or never taken: it had no window to roll over
		out.Set("error", "unknown: "+name+" returned no meters")
	}
	return out
}

// normalized is a reported meter as every reader of one expects it: with its elapsed% and pace.
func normalized(meter *run.Object, now float64) *run.Object {
	out := meter.Copy()
	resets, dated := run.Num(meter.Get("resets_at"))
	window, long := run.Num(meter.Get("window_secs"))
	out.Set("elapsed", nil)
	out.Set("pace", nil)
	if dated && long && resets > 0 && window > 0 {
		elapsed := 100 * (window - (resets - now)) / window
		if !(elapsed < 100) { // Python's min(100.0, x), NaN included
			elapsed = 100
		}
		elapsed = max(0, elapsed)
		spent, _ := number(meter.Get("used"))
		out.Set("elapsed", round(elapsed, 1))
		out.Set("pace", round(spent-elapsed, 1))
	}
	out.Set("exhausted", false)
	return out
}

// topPace is the greatest pace of those meters as written, nil where none has one.
func topPace(meters []any) any {
	var top any
	best := math.Inf(-1)
	for _, meter := range objects(meters) {
		if pace, ok := run.Num(meter.Get("pace")); ok && (top == nil || pace > best) {
			top, best = meter.Get("pace"), pace
		}
	}
	return top
}

// past is whether a meter's window has rolled over, so its used% answers for nothing.
func past(meter *run.Object, now float64) bool {
	resets, ok := run.Num(meter.Get("resets_at"))
	return ok && resets <= now
}

// session is whether a meter is the 5h session window.
func session(meter *run.Object) bool {
	return run.Equal(meter.Get("window_secs"), run.Float(sessionSecs))
}

// used is a meter's used% as Python compares it, 0 where it says none.
func used(meter *run.Object) float64 {
	value, _ := run.Num(meter.Get("used"))
	return value
}

// creditsLeft is the credits a reading still holds, +Inf for `unlimited`, 0 for none known.
func creditsLeft(prov *run.Object) float64 {
	if prov.Get("credits") == "unlimited" {
		return math.Inf(1)
	}
	if left, ok := number(prov.Get("credits")); ok && left > 0 {
		return left
	}
	return 0
}

// number is a JSON value as Python's usage._number takes it: a finite number, never a bool.
func number(value any) (float64, bool) {
	parsed, ok := run.Num(value)
	return parsed, ok && !math.IsInf(parsed, 0) && !math.IsNaN(parsed)
}

// numbers is whether each of those keys holds a number.
func numbers(object *run.Object, keys ...string) bool {
	for _, key := range keys {
		if _, ok := number(object.Get(key)); !ok {
			return false
		}
	}
	return true
}

// minus is a - b as Python subtracts the numbers, an int where both are.
func minus(a, b any) any {
	x, _ := a.(run.Number)
	y, _ := b.(run.Number)
	if first, ok := new(big.Int).SetString(string(x), 10); ok {
		if second, ok := new(big.Int).SetString(string(y), 10); ok {
			return run.Number(first.Sub(first, second).String())
		}
	}
	first, _ := run.Num(x)
	second, _ := run.Num(y)
	return run.Float(first - second)
}

// round is Python's round(x, places).
func round(x float64, places int) float64 {
	rounded, _ := strconv.ParseFloat(strconv.FormatFloat(x, 'f', places, 64), 64)
	return rounded
}

// text is Python's str() of a JSON value.
func text(value any) string {
	switch value := value.(type) {
	case string:
		return value
	case bool:
		if value {
			return "True"
		}
		return "False"
	case nil:
		return "None"
	}
	return run.Line(value)
}

// typeName is the name Python gives a JSON value's type.
func typeName(value any) string {
	switch value := value.(type) {
	case nil:
		return "NoneType"
	case bool:
		return "bool"
	case string:
		return "str"
	case []any:
		return "list"
	case run.Number:
		if strings.ContainsAny(string(value), ".eEIN") {
			return "float"
		}
		return "int"
	}
	return "dict"
}

// word is a character Python's \w matches.
func word(r rune) bool {
	return unicode.IsLetter(r) || unicode.IsNumber(r) || r == '_'
}

// object is a value that is a JSON object, else an empty one, as Python's usage._record.
func object(value any) *run.Object {
	if found, ok := value.(*run.Object); ok && found != nil {
		return found
	}
	return run.NewObject()
}

// objects is the JSON objects of a list.
func objects(value any) []*run.Object {
	var found []*run.Object
	items, _ := value.([]any)
	for _, item := range items {
		if each, ok := item.(*run.Object); ok {
			found = append(found, each)
		}
	}
	return found
}

// list is objects as a JSON list.
func list(objects []*run.Object) []any {
	items := []any{}
	for _, each := range objects {
		items = append(items, each)
	}
	return items
}

// values is an object's values, in its order.
func values(object *run.Object) []any {
	var found []any
	for _, key := range object.Keys() {
		found = append(found, object.Get(key))
	}
	return found
}

// fields is an object of those keys and values, in that order.
func fields(pairs ...any) *run.Object {
	object := run.NewObject()
	for i := 0; i < len(pairs); i += 2 {
		object.Set(pairs[i].(string), pairs[i+1])
	}
	return object
}
