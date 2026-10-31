package usage

import (
	"cmp"
	"fmt"
	"math"
	"slices"
	"strconv"
	"strings"
	"time"

	"agentkit/internal/run"
	"agentkit/internal/terminal"
)

const asOfAfter = 1800.0 // seconds a reading is old before `ak usage` says when it was taken

// signs are the currencies a balance is shown by the sign nobody misreads, else by its code.
var signs = map[string]string{"USD": "$", "EUR": "€", "GBP": "£"}

// Rows is a row per subscription as `ak usage` prints it, Python's usage.rows: its name and
// models, what its tightest week has left, the tokens that week holds, its price a month, when
// the shared week resets, how far the tightest week has run, what its session has left, the
// resets it holds, its headroom, budget and outlook, `-` for what it reports none of.  No
// reading Read takes measures what a week holds.
func (r *Readings) Rows() [][]string {
	var rows [][]string
	for _, name := range r.providers.Keys() {
		prov, src := object(r.providers.Get(name)), r.source(name)
		week := weekly(prov)
		var sess *run.Object
		for _, meter := range objects(prov.Get("meters")) {
			if session(meter) && (sess == nil || used(meter) > used(sess)) {
				sess = meter
			}
		}
		models, price := cmp.Or(strings.Join(src.Models, ", "), "-"), "-"
		if src.Price != nil {
			price = grouped(strconv.FormatFloat(*src.Price, 'f', -1, 64))
		}
		resets, counted := reading(prov, "resets")
		room, known := headroom(week)
		rows = append(rows, []string{name, models, percent(left(week)), "-", price,
			cmp.Or(resetWhen(r.sharedWeek(name, prov), r.now), "-"), percent(reading(week, "elapsed")),
			percent(left(sess)), fixed(resets, counted, 0), fixed(room, known, 1),
			budgetLabel(providerBudget(prov, r.now)), outlook(prov)})
	}
	return rows
}

// Notes is what `ak usage` prints under its table, Python's usage.render: each split week's two
// meters and, where they differ, each of its models' budget; each error but a refusal's, which
// says nothing; dim, the age of a reading over half an hour old with a meter still open; and
// each subscription's notes and credits.
func (r *Readings) Notes(dim func(string) string) []string {
	var notes []string
	names := r.providers.Keys()
	for _, name := range names {
		week, own := splitWeek(name, object(r.providers.Get(name)), r.models)
		if week == nil {
			continue
		}
		gap, _ := run.Num(minus(week.Get("used"), own.Get("used")))
		// the same polarity as the column; the gap stays in points of the week spent
		notes = append(notes, fmt.Sprintf("%s: weekly_all %s left, %s %s left, gap %s", name, percent(left(week)),
			own.Str("name"), percent(left(own)), strconv.FormatFloat(gap, 'g', 6, 64)))
		type budget struct {
			value float64
			why   string
		}
		var budgets []budget
		var shown []string
		for _, model := range r.source(name).Models {
			value, why := r.Budget(model)
			budgets, shown = append(budgets, budget{value, why}), append(shown, model+" "+budgetLabel(value, why))
		}
		if slices.ContainsFunc(budgets, func(each budget) bool { return each != budgets[0] }) {
			notes = append(notes, "  budget: "+strings.Join(shown, "; "))
		}
	}
	for _, name := range names {
		prov := object(r.providers.Get(name))
		if said := text(prov.Get("error")); prov.Truthy("error") && (prov.Get("probe_error") == nil || !refused(said)) {
			notes = append(notes, "note: "+name+" "+said)
		}
	}
	for _, name := range names {
		prov := object(r.providers.Get(name))
		open := slices.ContainsFunc(objects(prov.Get("meters")), func(meter *run.Object) bool { return !past(meter, r.now) })
		if at := asOf(prov, r.now); at != "" && open {
			notes = append(notes, dim("note: "+name+" "+at))
		}
	}
	for _, name := range names {
		for _, note := range object(r.providers.Get(name)).List("notes") {
			notes = append(notes, name+": "+text(note))
		}
	}
	for _, name := range names {
		if note := creditsNote(object(r.providers.Get(name))); note != "" {
			notes = append(notes, name+": "+note)
		}
	}
	return notes
}

// source is the provider of that name as the read asked it.
func (r *Readings) source(name string) source {
	at := slices.IndexFunc(r.sources, func(src source) bool { return src.Name == name })
	return r.sources[at]
}

// sharedWeek is the weekly meter every model of that provider draws on, Python's
// usage.shared_week: the tightest one read in a window still open that no model claims as its
// own cap; nil where there is none.
func (r *Readings) sharedWeek(name string, prov *run.Object) *run.Object {
	claimed := map[string]bool{}
	for _, model := range r.models {
		if model.Provider == name && model.Meter != "" {
			claimed[model.Meter] = true
		}
	}
	var worst *run.Object
	for _, meter := range objects(prov.Get("meters")) {
		if !session(meter) && numbers(meter, "used") && !past(meter, r.now) && !claimed[meter.Str("name")] &&
			(worst == nil || used(meter) > used(worst)) {
			worst = meter
		}
	}
	return worst
}

// outlook is when a reading runs dry at the rate its tightest week has been spent, Python's
// usage.outlook: `on track` where that outlasts the window.
func outlook(prov *run.Object) string {
	week := weekly(prov)
	room, known := headroom(week)
	elapsed, timed := reading(week, "elapsed")
	window, long := reading(week, "window_secs")
	switch {
	case prov.Truthy("exhausted"):
		return "exhausted"
	case prov.Truthy("on_credits"):
		return "on credits"
	case prov.Truthy("error") || !known:
		return "unknown"
	case !timed || !long || elapsed <= 0 || window <= 0:
		return "-" // nothing spent in no time: no rate to tell
	}
	rate := used(week) / (elapsed / 100 * window / 3600) // used% an hour
	hours := room * 100 / rate
	if rate <= 0 || hours >= (100-elapsed)/100*window/3600 {
		return "on track"
	}
	return fmt.Sprintf("runs out in ~%dd", max(1, int(math.RoundToEven(hours/24))))
}

// headroom is what a weekly meter has left unspent, as a fraction, false where it reports none.
func headroom(week *run.Object) (float64, bool) {
	spent, ok := reading(week, "used")
	return round(max(0, (100-spent)/100), 3), ok
}

// left is a meter's used% turned to what it has left, false where it reports none.
func left(meter *run.Object) (float64, bool) {
	spent, ok := reading(meter, "used")
	return max(0, min(100, 100-spent)), ok
}

// reading is the number a meter or record holds under key, false where it holds none.
func reading(meter *run.Object, key string) (float64, bool) {
	if meter == nil {
		return 0, false
	}
	return number(meter.Get(key))
}

// resetWhen is when a meter's window opens again in the reader's own time, Python's
// usage.reset_when: `Fri 14:00`, a date more than six days out in a window longer than a week,
// or `in 3d` where it says only how long; "" where it says neither.
func resetWhen(meter *run.Object, now float64) string {
	if at, ok := reading(meter, "resets_at"); ok && at > now {
		window, _ := reading(meter, "window_secs")
		if at-now > 6*86400 && !(window != 0 && window <= 7*86400) {
			return local(at).Format("2 Jan")
		}
		return local(at).Format("Mon 15:04")
	}
	if secs, ok := reading(meter, "resets_in"); ok && secs > 0 {
		return "in " + terminal.FormatAge(secs)
	}
	return ""
}

// asOf is `as of 14:02`, `as of Fri 14:02` where not today, for a reading over half an hour
// old, Python's usage.as_of; "" for a younger one, or one with no moment to tell.
func asOf(prov *run.Object, now float64) string {
	at, ok := number(taken(prov))
	if !ok || now-at <= asOfAfter {
		return ""
	}
	then, today := local(at), local(now)
	if then.YearDay() != today.YearDay() || then.Year() != today.Year() {
		return "as of " + then.Format("Mon 15:04")
	}
	return "as of " + then.Format("15:04")
}

// local is a moment in the reader's own time, to the second, as Python's time.localtime has it.
func local(at float64) time.Time {
	return time.Unix(int64(math.Floor(at)), 0)
}

// creditsNote is `62,469 credits left`, `$12.40 credits left` in a currency, or `unlimited
// credits`, Python's usage.credits_note; "" where a reading holds none.
func creditsNote(prov *run.Object) string {
	credits := creditsLeft(prov)
	switch {
	case credits == 0:
		return ""
	case math.IsInf(credits, 1):
		return "unlimited credits"
	case prov.Truthy("currency"):
		sign, known := signs[prov.Str("currency")]
		if !known {
			sign = text(prov.Get("currency")) + " "
		}
		return strings.TrimSuffix(sign+grouped(fmt.Sprintf("%.2f", credits)), ".00") + " credits left"
	}
	whole, unit := math.Trunc(credits), " credits left"
	if whole == 1 {
		unit = " credit left"
	}
	return grouped(fmt.Sprintf("%.0f", whole)) + unit
}

// budgetLabel is a budget as `ak usage` words it: `1.4 slack`, `0.8 ahead`, `1.0 in step`, or
// `unknown` where there is a why.
func budgetLabel(budget float64, why string) string {
	if why != "" {
		return "unknown"
	}
	budget, word := round(budget, 1), "in step"
	if budget > 1 {
		word = "slack"
	} else if budget < 1 {
		word = "ahead"
	}
	return strconv.FormatFloat(budget, 'f', 1, 64) + " " + word
}

// percent is `60%`, `-` where there is no number.
func percent(value float64, ok bool) string {
	if !ok {
		return "-"
	}
	return fixed(value, ok, 0) + "%"
}

// fixed is a number to that many places, `-` where there is none.
func fixed(value float64, ok bool, places int) string {
	if !ok {
		return "-"
	}
	return strconv.FormatFloat(value, 'f', places, 64)
}

// grouped is a number's text with a comma between each three digits of its whole part, as
// Python's `,` format writes it.
func grouped(number string) string {
	end := strings.IndexByte(number, '.')
	if end < 0 {
		end = len(number)
	}
	for at := end - 3; at > 0 && number[at-1] != '-'; at -= 3 {
		number = number[:at] + "," + number[at:]
	}
	return number
}
