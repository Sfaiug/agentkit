package harness

import (
	"cmp"
	"math"
	"slices"
	"strconv"

	"agentkit/internal/run"
)

// claudeResets is the usage-limit resets the endpoint's reading holds and their kinds, as
// claude.sh's jq counts them and Claude Code 2.1.322 sorts them: an eligible login's unpaused
// grants with resets left, each of the kind of what it refills.  One that gives its use back to
// the week refills the scoped weekly cap, whatever its `type`, and is named as that cap is (the
// first weekly limit's scope, else `scoped`); any other is its `type`, or with none what it clears
// says.  The kinds come in Claude Code's order, one `usable` where one of its grants can be spent
// now.  A block of a shape never seen holds no resets, and costs the meters nothing.
func claudeResets(reading any) (run.Number, []any) {
	fable := ""
	limits, _ := items(at(reading, "limits"))
	for _, limit := range limits {
		if fable == "" && at(limit, "group") == "weekly" {
			fable = claudeScope(limit)
		}
	}
	fable = cmp.Or(fable, "scoped")
	type grant struct {
		kind   string
		left   float64
		usable bool
	}
	var grants []grant
	if block, _ := at(reading, "cedar_ember").(*run.Object); block != nil && block.Get("eligible") == true {
		listed, _ := items(block.Get("grants"))
		for _, each := range listed {
			held, _ := each.(*run.Object)
			if held == nil {
				continue
			}
			left, counted := run.Num(held.Get("resets_left"))
			if held.Get("paused") == true || !counted || !(left > 0) {
				continue
			}
			kind, named := held.Get("type").(string)
			if held.Get("gives_back_weekly") == true {
				kind, named = fable, false
			} else if !named {
				clears := held.Get("clears")
				if clears == nil || clears == false {
					clears = []any{}
				}
				list, _ := clears.([]any)
				cleared, iterable := items(clears)
				switch {
				case len(list) == 1 && list[0] == "five_hour":
					kind = "session"
				case !iterable:
					return "0", []any{}
				case slices.Contains(cleared, any("five_hour")):
					kind = "full"
				default:
					kind = "weekly"
				}
				named = true
			}
			if named {
				kind = map[string]string{"session": "5-hour", "weekly": "weekly", "full": "full"}[kind]
			}
			grants = append(grants, grant{kind, left, held.Get("usable_now") == true})
		}
	}
	total, kinds := 0.0, []any{}
	for _, each := range grants {
		total += each.left
	}
	for _, kind := range []string{"5-hour", "weekly", fable, "full"} {
		left, usable, found := 0.0, false, false
		for _, each := range grants {
			if each.kind == kind {
				left, usable, found = left+each.left, usable || each.usable, true
			}
		}
		if found {
			kinds = append(kinds, run.Fields("kind", kind, "left", jqNumber(left), "usable", usable))
		}
	}
	return jqNumber(total), kinds
}

// claudeScope is the model or surface a limit is the own cap of, by its display name; "" for none.
func claudeScope(limit any) string {
	for _, whose := range []string{"model", "surface"} {
		if name, _ := at(limit, "scope", whose, "display_name").(string); name != "" {
			return name
		}
	}
	return ""
}

// jqNumber is a number as jq writes one it worked out: an integral one's digits.
func jqNumber(value float64) run.Number {
	if value == math.Trunc(value) && math.Abs(value) < 1e17 {
		return run.Number(strconv.FormatFloat(value, 'f', 0, 64))
	}
	return run.Float(value)
}

// items is jq's `.[]` of value: an array's items, an object's values in order; false for anything
// else.
func items(value any) ([]any, bool) {
	switch value := value.(type) {
	case []any:
		return value, true
	case *run.Object:
		var values []any
		for _, key := range value.Keys() {
			values = append(values, value.Get(key))
		}
		return values, true
	}
	return nil, false
}
