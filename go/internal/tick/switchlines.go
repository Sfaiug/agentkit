package tick

import (
	"cmp"
	"context"
	"fmt"
	"path/filepath"
	"slices"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"

	"agentkit/internal/config"
	"agentkit/internal/features"
	"agentkit/internal/plan"
	"agentkit/internal/run"
	"agentkit/internal/seat"
)

// A handing is what one checkout's switch list hands its seats, read before anything is written:
// the WARN of a list unread, else what is due and the line each switch takes in its seat.
type handing struct {
	checkout, warn, about string
	lines                 []switchLine
	left                  []string // the switches no seat takes, by id
}

type switchLine struct{ seat, id, what, check string }

// A switchDue is a switch its list shows proven, or on for everyone with no everyone_since.
type switchDue struct {
	id     string
	at     time.Time
	proven bool
}

// handed is what the checkout's list hands its seats now (retire.hand): a line for each switch
// due, in the newest seat whose open plan names it, else the newest at work.  errLeft where Go
// would read the list, a seat's word or a line otherwise than Python does.
func handed(checkout string, now time.Time) (handing, error) {
	hand, name := handing{checkout: checkout}, filepath.Base(checkout)
	rows, listed, why := features.Listed(checkout)
	if !listed {
		hand.warn = fmt.Sprintf("WARN %s: its switches are unread, so none was planned (%s)", name, cmp.Or(why, "no list"))
		return hand, nil
	}
	var proved, undated []switchDue
	for _, row := range rows {
		at, on, err := features.Since(row)
		if err != nil {
			return hand, errLeft
		}
		if each := (switchDue{run.Text(row.Get("id")), at, on}); on && now.Sub(at) >= features.Proven {
			proved = append(proved, each)
		} else if !on && row.Get("everyone") == true {
			undated = append(undated, each)
		}
	}
	// longest on for everyone first
	slices.SortStableFunc(proved, func(a, b switchDue) int { return cmp.Or(a.at.Compare(b.at), strings.Compare(a.id, b.id)) })
	var about []string
	if len(proved) > 0 {
		about = append(about, "proven switches "+ids(proved))
	}
	if len(undated) > 0 {
		about = append(about, "on for everyone with no everyone_since "+ids(undated))
	}
	hand.about = strings.Join(about, "; ")
	every := slices.Concat(proved, undated)
	if len(every) == 0 {
		return hand, nil
	}
	seats, plans, working := seat.Under(checkout), map[string]string{}, ""
	for _, each := range seats {
		plans[each] = plan.Planned(each)
	}
	for _, each := range seats {
		word, _ := seat.Published(each)
		if word == "" {
			return hand, errLeft // Python decides a word from what there is
		}
		if word == "working" {
			working = each
			break
		}
	}
	// a seat whose open plan names the switch already has it in hand; one at rest is never told
	// of one, so its word would only turn to `needs you`
	owner := map[string]string{}
	for _, each := range every {
		if _, found := owner[each.id]; found {
			continue
		}
		owner[each.id] = working
		if at := slices.IndexFunc(seats, func(name string) bool { return naming(plans[name], each.id) }); at >= 0 {
			owner[each.id] = seats[at]
		}
		if owner[each.id] == "" {
			hand.left = append(hand.left, each.id)
		}
	}
	for _, each := range every {
		line := switchLine{owner[each.id], each.id, outcome(name, each), features.Check(each.id, each.proven)}
		if line.seat == "" {
			continue
		}
		// words Python's plan.add refuses
		if strings.Contains(line.what, "·") || strings.Contains(line.check, "`") || len(config.SplitLines(line.check)) != 1 {
			return hand, errLeft
		}
		hand.lines = append(hand.lines, line)
	}
	return hand, nil
}

// hand writes the checkout's lines and says what it planned; true where each switch due has its
// line, so its list is not read again for retireAgain.
func (t *ticking) hand(hand handing) bool {
	if hand.warn != "" {
		t.log.line(hand.warn)
		return false
	}
	if hand.about == "" {
		return false
	}
	var written, refused []string
	for _, line := range hand.lines {
		if _, err := plan.Add(context.Background(), line.seat, hand.checkout, line.what, line.check); err != nil {
			refused = append(refused, fmt.Sprintf("%s: %s: %s", line.seat, line.id, config.PyError(err)))
		} else if !slices.Contains(written, line.seat) {
			written = append(written, line.seat)
		}
	}
	name := filepath.Base(hand.checkout)
	if len(refused) > 0 {
		t.log.line(fmt.Sprintf("WARN %s: %s; not planned: %s", name, hand.about, strings.Join(refused, "; ")))
		return false
	}
	done := ""
	if len(written) > 0 {
		done = "; planned in " + strings.Join(written, ", ")
	}
	if len(hand.left) > 0 {
		t.log.line(fmt.Sprintf("%s: %s%s; no seat at work to plan %s in", name, hand.about, done, strings.Join(hand.left, ", ")))
		return false
	}
	t.log.line(fmt.Sprintf("%s: %s%s", name, hand.about, done))
	return true
}

// outcome is the plan line's words for that switch (retire.outcome): what the seat is to make true.
func outcome(project string, switched switchDue) string {
	name := config.Fold(switched.id)
	if switched.proven {
		return fmt.Sprintf("%s's switch %s is out of the code: on for everyone since %s, so proven, "+
			"and everyone keeps the feature for good", project, name, switched.at.Local().Format("2 Jan"))
	}
	return fmt.Sprintf("%s's switch list gives %s an everyone_since (when it last went on for everyone, "+
		"ISO 8601 UTC, or null while it is not), so ak can tell when it is proven", project, name)
}

func ids(found []switchDue) string {
	var names []string
	for _, each := range found {
		names = append(names, each.id)
	}
	return strings.Join(names, ", ")
}

// naming is whether text holds id as a word of its own, as retire.owners reads it: no letter,
// number, `_` or `-` on either side.
func naming(text, id string) bool {
	for at := 0; at <= len(text); at++ {
		found := strings.Index(text[at:], id)
		if found < 0 {
			return false
		}
		at += found
		before, _ := utf8.DecodeLastRuneInString(text[:at])
		after, _ := utf8.DecodeRuneInString(text[at+len(id):])
		if !wordy(before) && !wordy(after) {
			return true
		}
	}
	return false
}

func wordy(r rune) bool { return r == '_' || r == '-' || unicode.IsLetter(r) || unicode.IsNumber(r) }
