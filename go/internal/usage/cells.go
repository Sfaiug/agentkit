package usage

import (
	"math"
	"regexp"
	"strconv"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// The first match of what a probe's error says is why a row has no reading, Python's menu.UNREAD.
var unreadWords = []struct {
	pattern *regexp.Regexp
	words   string
}{{regexp.MustCompile(`already reset`), "window reset"}, {regexp.MustCompile(`without a name`), "bad reading"},
	{regexp.MustCompile(`returned no meters`), "no reading yet"}}

// Cached is state/usage.json as it stands: nobody is asked and nothing is written.
func Cached() (*Readings, error) {
	models, err := config.Entries()
	if err != nil {
		return nil, err
	}
	return &Readings{providers: object(object(read()).Get("providers")), models: models, now: clock()}, nil
}

// Cell is what a subscription's cell on the ak screen says, Python's menu.usage_cells: left is 1 to
// 100 and said `NN% left`; 0 for a spent week on credits, which count as usage left, said being
// them; or -1 with said `empty until <when>`, or `—` and why.  An account of "" is the provider's
// single reading.
func (r *Readings) Cell(provider, account string) (left int, said string) {
	prov := r.login(provider, account)
	week := r.sharedWeek(provider, prov)
	if week == nil {
		return -1, "—  " + r.unread(prov)
	}
	spare, _ := reading(week, "used")
	share := int(math.RoundToEven(max(0, min(100, 100-spare))))
	credits := creditsNote(prov)
	switch {
	case share > 0:
		return share, strconv.Itoa(share) + "% left"
	case credits != "":
		return 0, credits
	}
	if when := resetWhen(week, r.now); when != "" {
		return -1, "empty until " + when
	}
	return -1, "empty"
}

// login is that subscription's reading, the provider's single one for an account of "".
func (r *Readings) login(provider, account string) *run.Object {
	prov := object(r.providers.Get(provider))
	if account != "" {
		prov = object(object(prov.Get("accounts")).Get(account))
	}
	return prov
}

// unread is why a reading has no shared week to draw, Python's menu.unread.  Only the harness's own
// `auth` verb saying no is `no login`.
func (r *Readings) unread(prov *run.Object) string {
	var weeks, open []*run.Object
	for _, meter := range objects(prov.Get("meters")) {
		if session(meter) {
			continue
		}
		weeks = append(weeks, meter)
		if numbers(meter, "used") && !past(meter, r.now) {
			open = append(open, meter)
		}
	}
	allPast := len(weeks) > 0
	for _, meter := range weeks {
		allPast = allPast && past(meter, r.now)
	}
	said := text(prov.Get("error"))
	if !prov.Truthy("error") {
		said = ""
	}
	switch {
	case len(open) > 0:
		return "no shared week"
	case prov.Truthy("none") && said == "":
		return "no meter"
	case allPast:
		return "window reset"
	case len(weeks) > 0:
		return "bad reading"
	case prov.Get("logged_in") == false:
		return "no login"
	}
	for _, each := range unreadWords {
		if each.pattern.MatchString(said) {
			return each.words
		}
	}
	switch {
	case prov.Truthy("meters"):
		return "no weekly meter"
	case said != "":
		return "not reached"
	}
	return "no reading yet"
}
