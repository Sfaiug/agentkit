package features

import (
	"context"
	"errors"
	"regexp"
	"strconv"
	"strings"
	"time"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	record "agentkit/internal/run"
)

// Proven is how long a switch is on for everyone before it is proven, Python's retire.PROVEN: the
// owner's two weeks.
const Proven = 14 * 24 * time.Hour

// ErrStamp is an `everyone_since` Go cannot read as Python's datetime.fromisoformat reads it.
var ErrStamp = errors.New("an everyone_since Go cannot read as Python does")

// stamp is ISO 8601 as a deploy writes it, each form one Python's fromisoformat reads alike: a
// date, then a time to the minute, second or past it, with `Z`, an offset (`date +%z`'s too), or
// none for UTC.
var stamp = regexp.MustCompile(`^([0-9]{4})-([0-9]{2})-([0-9]{2})(?:[T ]([0-9]{2}):([0-9]{2})` +
	`(?::([0-9]{2})(?:[.,]([0-9]+))?)?(?:Z|([+-])([0-9]{2}):?([0-9]{2}))?)?$`)

// retire.check's line around the path of Python ak's checkout, which Python's retire.check_main
// is read from.
const lead, call = `python3 -c "import sys; sys.path.insert(0, `, `); from agentkit import retire; retire.check_main()" `

// Listed is the rows the checkout's `list` answers now (menu.switch_rows); false for no list,
// with the one line saying why where there is one.
func Listed(checkout string) ([]*record.Object, bool, string) {
	answer, why := own(checkout, "list")
	rows, listed := objects(answer)
	return rows, listed, why
}

// Since is when the row last went on for everyone (retire.since), and false while it is not or
// its stamp reads as no time; ErrStamp for one Go cannot read.
func Since(row *record.Object) (time.Time, bool, error) {
	text, stamped := row.Get("everyone_since").(string)
	if row.Get("everyone") != true || !stamped {
		return time.Time{}, false, nil
	}
	part := stamp.FindStringSubmatch(text)
	if part == nil {
		return time.Time{}, false, ErrStamp
	}
	n := make([]int, len(part))
	for i, digits := range part[1:] {
		n[i+1], _ = strconv.Atoi(digits)
	}
	// Python keeps a second's first six digits, dropping the rest
	micro, _ := strconv.Atoi((part[7] + "000000")[:6])
	offset := (n[9]*60 + n[10]) * 60
	if part[8] == "-" {
		offset = -offset
	}
	at := time.Date(n[1], time.Month(n[2]), n[3], n[4], n[5], n[6], micro*1000, time.FixedZone("", offset))
	// a field out of its range Python refuses where Go's time rolls it over
	if n[1] < 1 || at.Year() != n[1] || int(at.Month()) != n[2] || at.Day() != n[3] || n[4] > 23 || n[5] > 59 || n[6] > 59 || n[9] > 23 || n[10] > 59 {
		return time.Time{}, false, ErrStamp
	}
	return at, true, nil
}

// Check is the plan line's check for the switch (retire.check), as Python ak writes it, so Go and
// Python find one line in the plan: it fails while the list still shows the switch (proven), or
// shows it on for everyone with no readable `everyone_since` (unproven).
func Check(id string, proven bool) string {
	kind := "unproven"
	if proven {
		kind = "proven"
	}
	return lead + commandhelp.Quote(config.Repo()) + call + commandhelp.ShellJoin([]string{id}) + " " + kind
}

// Checked is whether check is Check's, and then whether it passes in tree, a checkout of the
// project, its list asked in env, the check's environment: read here, as no Python ak may be
// there to run it.  A list unread fails it; a stamp Go cannot read leaves it to run as written.
func Checked(tree, check string, env []string) (passed, ours bool) {
	at := strings.LastIndex(check, call)
	if !strings.HasPrefix(check, lead) || at < 0 {
		return false, false
	}
	words := check[at+len(call):]
	quoted, kind := words, ""
	if cut := strings.LastIndex(words, " "); cut >= 0 {
		quoted, kind = words[:cut], words[cut+1:]
	}
	id := quoted
	if len(quoted) > 1 && strings.HasPrefix(quoted, "'") && strings.HasSuffix(quoted, "'") {
		id = strings.ReplaceAll(quoted[1:len(quoted)-1], `'"'"'`, `'`)
	}
	// only the very words retire.check writes
	if commandhelp.ShellJoin([]string{id})+" "+kind != words || kind != "proven" && kind != "unproven" {
		return false, false
	}
	answer, _ := run(context.Background(), tree, env, "list")
	rows, listed := objects(answer)
	if !listed {
		return false, true
	}
	for _, row := range rows {
		if record.Text(row.Get("id")) != id {
			continue
		}
		_, on, err := Since(row)
		if kind == "unproven" && err != nil {
			return false, false
		}
		if kind == "proven" || row.Get("everyone") == true && !on {
			return false, true
		}
	}
	return true, true
}
