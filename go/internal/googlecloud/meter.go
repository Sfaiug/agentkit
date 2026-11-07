package googlecloud

import (
	"errors"
	"io/fs"
	"path/filepath"
	"strings"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// The meter is this month's spend on the machines ak rents, which the tick moves on at each pass,
// in Python's google-cloud-ledger.json: Google's billing export is hours late.

// meter is the meter as the tick left it, at nothing before its first; false where it cannot be
// read, as losing the month's total never reads as money left (google_cloud._ledger).
func meter() (*run.Object, bool) {
	ledger, err := run.ReadJSON(meterPath())
	if errors.Is(err, fs.ErrNotExist) {
		return run.Fields("answered", 0, "spent", 0, "machines", run.NewObject()), true
	}
	return ledger, readable(ledger)
}

// readable is whether the meter holds only amounts ak could have written: a partial or corrupt
// one never supplies an amount.
func readable(ledger *run.Object) bool {
	amount := func(value any) bool {
		number, ok := run.Num(value)
		return ok && possible(number)
	}
	if ledger == nil || ledger.Dict("machines") == nil || !amount(ledger.Get("answered")) || !amount(ledger.Get("spent")) {
		return false
	}
	for _, key := range ledger.Dict("machines").Keys() {
		one := ledger.Dict("machines").Dict(key)
		if one == nil || !amount(one.Get("price")) || !amount(one.Get("until")) || one.Has("from") && !amount(one.Get("from")) {
			return false
		}
	}
	return true
}

// possible is whether ak could have written number: a NaN passes any cap.
func possible(number float64) bool { return number >= 0 && number < 1e12 }

// moved is the meter moved on to now, Google listing listed, at the prices offered of each type
// in its region (google_cloud._moved). Each machine listed is charged since the last answer, or
// since its creation where it is new or was on the meter by name, at the dearer of the price the
// meter holds for it and its type's there, else the dearest offered; one gone is paid up to its
// end. One on the meter by name, `from` when it was asked for, that Google has not listed stays
// until its end and is then paid whole: no listing can show it gone. Only this month's time
// counts, in UTC. A number carried over keeps the form it was written in, int or float, as
// Python's does.
func moved(ledger *run.Object, listed []Machine, now float64, prices map[[2]string]float64) *run.Object {
	month := time.Unix(int64(now), 0).UTC()
	start := float64(time.Date(month.Year(), month.Month(), 1, 0, 0, 0, 0, time.UTC).Unix())
	since, _ := ledger.Num("answered")
	var spent any = run.Number("0")
	total := 0.0
	if since >= start {
		spent = ledger.Get("spent")
		total, _ = run.Num(spent)
	}
	pay := func(price any, from, to float64) {
		hourly, _ := run.Num(price)
		total += hourly * max(0, to-max(from, start)) / 3600
		spent = run.Float(total)
	}
	var dearest any = run.Number("0")
	for _, price := range prices {
		if most, _ := run.Num(dearest); price > most {
			dearest = run.Float(price)
		}
	}
	kept, machines := ledger.Dict("machines").Copy(), run.NewObject()
	for _, one := range listed {
		key := one.ID
		if !kept.Has(key) {
			key = one.Name
		}
		old := kept.Dict(key)
		kept.Delete(key)
		var held, offered any = run.Number("0"), dearest
		if old != nil {
			held = old.Get("price")
		}
		if price, ok := prices[[2]string{one.Type, regionOf(one.Zone)}]; ok {
			offered = run.Float(price)
		}
		price := held // the first of two equal, as Python's max
		was, _ := run.Num(held)
		if dearer, _ := run.Num(offered); dearer > was {
			price = offered
		}
		machines.Set(one.ID, run.Fields("price", price, "until", one.Until))
		from := one.Created
		if old != nil && !old.Has("from") {
			from = since
		}
		pay(price, from, now)
	}
	for _, key := range kept.Keys() {
		gone := kept.Dict(key)
		until, _ := gone.Num("until")
		if gone.Has("from") && now < until {
			machines.Set(key, gone)
			continue
		}
		from := since
		if gone.Has("from") {
			from, _ = gone.Num("from")
		}
		pay(gone.Get("price"), from, min(now, until))
	}
	return run.Fields("answered", now, "spent", spent, "machines", machines)
}

// regionOf is a zone's region, as Google names its zones: europe-west4-a is in europe-west4.
func regionOf(zone string) string {
	if cut := strings.LastIndexByte(zone, '-'); cut >= 0 {
		return zone[:cut]
	}
	return zone
}

func meterPath() string { return filepath.Join(config.Home(), "state", "google-cloud-ledger.json") }
