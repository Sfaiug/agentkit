package usage

import (
	"maps"
	"math"
	"slices"
	"strconv"
	"strings"
	"unicode"

	"agentkit/internal/run"
)

// A Note is something the line under the ak screen's grid says of a subscription, ranked by how much
// it is worth keeping where only some fit, the lowest first (menu.fitting).
type Note struct {
	Rank int
	Text string
}

// Detail is what the line under the grid says of that subscription's reading, in the order the line
// reads it (menu.usage_detail): why it has no week to draw; else the credits it holds, when its week
// resets, the resets in hand, each model's own cap that differs, its 5-hour window, why its last
// probe failed and how old the reading is, each where it applies.
func (r *Readings) Detail(provider, account string) []Note {
	prov := r.login(provider, account)
	week := r.sharedWeek(provider, prov)
	if week == nil {
		return []Note{{0, r.unread(prov)}}
	}
	resets := ""
	if when := resetWhen(week, r.now); when != "" {
		resets = "resets " + when
	}
	notes := []Note{{-1, creditsNote(prov)}, {0, resets}, {1, inHand(prov)}}
	notes = append(notes, r.scoped(provider, prov, week)...)
	notes = append(notes, sessionNote(prov, r.now), Note{1, fault(prov)}, Note{1, asOf(prov, r.now)})
	return slices.DeleteFunc(notes, func(note Note) bool { return note.Text == "" })
}

// InHand is `1 reset in hand`, `2 resets in hand`: the usage-limit resets that subscription holds for
// the owner to spend on `c`; "" with none, or none known (menu.in_hand).
func (r *Readings) InHand(provider, account string) string { return inHand(r.login(provider, account)) }

func inHand(prov *run.Object) string {
	held, _ := number(prov.Get("resets"))
	switch {
	case int(held) == 1:
		return "1 reset in hand"
	case int(held) > 0:
		return strconv.Itoa(int(held)) + " resets in hand"
	}
	return ""
}

// scoped is `Fable 41%` for each week one model has to itself whose share left is not the shared
// week's: a cap reading the same says nothing the cell has not (menu.scoped_notes).
func (r *Readings) scoped(provider string, prov, week *run.Object) []Note {
	names := slices.Sorted(maps.Keys(r.models))
	var notes []Note
	for _, meter := range objects(prov.Get("meters")) {
		if session(meter) || !numbers(meter, "used") || past(meter, r.now) || shareLeft(meter) == shareLeft(week) {
			continue
		}
		for _, name := range names {
			if model := r.models[name]; model.Provider == provider && model.Meter == meter.Str("name") {
				first := []rune(strings.ToLower(name))
				first[0] = unicode.ToUpper(first[0])
				notes = append(notes, Note{3, string(first) + " " + strconv.Itoa(shareLeft(meter)) + "%"})
				break
			}
		}
	}
	return notes
}

// shareLeft is what a meter has left, as its cell says it: a whole number of percent.
func shareLeft(meter *run.Object) int {
	return int(math.RoundToEven(max(0, min(100, 100-used(meter)))))
}

// sessionNote is what is left of the 5-hour window furthest along that has not rolled over: `5h 40%
// left`, or once spent, ranked first, when it opens again, `5h spent until 14:00` (menu.session_note).
func sessionNote(prov *run.Object, now float64) Note {
	var window *run.Object
	for _, meter := range objects(prov.Get("meters")) {
		if session(meter) && numbers(meter, "used") && !past(meter, now) && (window == nil || used(meter) > used(window)) {
			window = meter
		}
	}
	if window == nil {
		return Note{}
	}
	if used(window) < 100 {
		return Note{2, "5h " + strconv.Itoa(shareLeft(window)) + "% left"}
	}
	when := resetWhen(window, now)
	switch {
	case strings.Contains(when, ":"):
		return Note{-1, "5h spent until " + when[strings.LastIndexByte(when, ' ')+1:]}
	case strings.HasPrefix(when, "in "):
		return Note{-1, "5h spent " + when}
	case when != "":
		return Note{-1, "5h spent until " + when}
	}
	return Note{-1, "5h spent"}
}

// fault is `? <reason>`, the adapter's own line for a probe that failed, "" for none: words that
// only say the endpoint refused say nothing, the reading's age saying the rest (menu.fault).
func fault(prov *run.Object) string {
	said := text(prov.Get("error"))
	if !prov.Truthy("error") || prov.Get("probe_error") != nil && refused(said) {
		return ""
	}
	return strings.TrimSpace("? " + strings.TrimPrefix(strings.Join(strings.Fields(said), " "), "unknown: "))
}
