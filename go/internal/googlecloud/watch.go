package googlecloud

import (
	"math"
	"os"
	"path/filepath"
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

const freshFor = 86400 // seconds offers are kept: a listing takes a minute

// Watch is the tick's pass over the machines ak rents, as Python's google_cloud.watch, run while
// ak may rent with work marked and wherever Google's key exists, given the line asking a machine
// how long it has held nothing (helper.Line's `idle`: package helper imports this one). The meter
// moves on to what Google lists, ssh asks each machine listed with an address, and each listed past
// its end, with no price kept, past the cap, with no work marked still starting or idle at all, or
// idle idleFor goes back, the first reason said; the routes are written anew, those that answered
// set up serving. Then, while ak may rent with work marked, offers kept a day or without zones are
// listed anew, and a need noted, while no machine comes up, rents (rent). A need noted is taken.
// False, nothing written, leaves the pass to Python: marks Go cannot read, or a need noted while ak
// may rent with work marked and Google lists a quota limit in the regions offered, which Python's
// rent counts machines against.
func Watch(line string) (bool, error) {
	active, cap := config.CloudBudget()
	work, known := config.MachineWork("")
	if !known {
		return false, nil
	}
	renting := active && len(work) > 0
	_, unkeyed := os.Stat(filepath.Join(config.Home(), "secrets", key))
	asked := renting || unkeyed == nil // Python's goes no further where neither
	var listed []Machine
	var at float64
	var err error
	if asked {
		if listed, err = Rented(); err == nil {
			at, err = now()
		}
	}
	if !asked || err != nil {
		noted(work)
		return true, err
	}
	keptAt, offered := Kept()
	prices := map[[2]string]float64{}
	for _, o := range offered {
		if possible(o.Hourly) {
			prices[[2]string{o.Name, o.Region}] = o.Hourly
		}
	}
	ledger, read := meter()
	// a meter that cannot be read is past any cap, leaves nothing, and is kept as it is
	spent, money := math.Inf(1), math.Inf(-1)
	if read {
		ledger = moved(ledger, listed, at, prices)
		spent, _ = ledger.Num("spent")
		money = left(cap, spent, ledger, at)
	}
	// Listed before anything is written, as a need's limits are read in the regions the rent takes.
	// A listing that fails leaves the offers kept, and the calls after it their own, as Python's
	// pass gives back before it lists.
	stale := renting && (!possible(keptAt) || at-keptAt >= freshFor ||
		slices.ContainsFunc(offered, func(o Offer) bool { return len(o.Zones) == 0 }))
	var listing error
	if stale {
		was := unanswered
		var fresh []Offer
		if fresh, listing = Offers(); listing == nil {
			offered = fresh
		}
		unanswered = was
	}
	if _, err := os.Lstat(needPath()); renting && err == nil && len(limits(offered)) > 0 {
		return false, nil
	}
	wanted := noted(work)
	held := idle(listed, line)
	var late []any
	var reached []Machine
	for _, machine := range listed {
		seconds := held[machine.ID] // 0 for one that did not answer
		starting := machine.Address == "" || seconds < 0
		why := ""
		switch {
		case at >= machine.Until:
			why = "past its end"
		case len(prices) == 0:
			why = "with no price kept"
		case spent > cap:
			why = "past the cap"
		case len(work) == 0 && (starting || seconds > 0):
			why = "no work marked"
		case seconds >= idleFor:
			why = "idle"
		default:
			if machine.Address != "" {
				reached = append(reached, machine)
			}
			continue
		}
		said := machine.Name + " listed " + why + ", given back"
		if err := GiveBack(machine); err != nil {
			said = machine.Name + " listed " + why + ", not given back: " + err.Error()
		}
		late = append(late, said)
	}
	err = serve(reached, held)
	if err == nil {
		err = save(latePath(), run.Encode(late)+"\n")
	}
	if err == nil && read {
		err = save(meterPath(), run.Encode(ledger)+"\n")
	}
	if err != nil || !renting {
		return true, err
	}
	if stale {
		if err = listing; err == nil {
			err = Keep(offered)
		}
	}
	if err != nil || wanted == 0 || !read || comingUp(ledger, listed, held, at) {
		return true, err
	}
	said, err := rent(ledger, wanted, cap, money, offered, listed)
	if err != nil {
		return true, err
	}
	return true, save(latePath(), run.Encode(append(late, said))+"\n")
}

// save replaces a state file whole through its .tmp, as Python's config._write_json and _serve
// do: a reader never sees half of it, and the tick's lock keeps it to one writer.
func save(path, text string) error {
	tmp := strings.TrimSuffix(path, filepath.Ext(path)) + ".tmp"
	if err := os.WriteFile(tmp, []byte(text), 0o666); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}
