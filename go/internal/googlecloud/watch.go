package googlecloud

import (
	"math"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

const freshFor = 86400 // seconds offers are kept: a listing takes a minute

// Watch is the tick's pass over the machines ak rents, as Python's google_cloud.watch, run while
// ak may rent with work marked and wherever Google's key exists: the meter moved on to what Google
// lists, and each machine listed past its end, with no price kept, past the cap or, with no work
// marked, still starting given back, the first reason said; then, while ak may rent with work
// marked, offers kept a day or without zones listed anew. A need noted while ak may not rent is
// taken. False, nothing written, leaves the pass to Python: marks Go cannot read, a need noted
// while ak may rent with work marked, or a machine listed with an address, which ssh reaches.
func Watch() (bool, error) {
	active, cap := config.CloudBudget()
	work, known := config.MachineWork("")
	renting := active && len(work) > 0
	need := filepath.Join(config.Home(), "state", "google-cloud-need")
	if _, err := os.Lstat(need); !known || renting && err == nil {
		return false, nil
	}
	_, unkeyed := os.Stat(filepath.Join(config.Home(), "secrets", key))
	asked := renting || unkeyed == nil // Python's goes no further where neither
	var listed []Machine
	var err error
	if asked {
		listed, err = Rented()
		if slices.ContainsFunc(listed, func(one Machine) bool { return one.Address != "" }) {
			return false, nil
		}
	}
	if !renting {
		os.Rename(need, need+".taken") // no rent comes of it: a suite noting next notes anew
	}
	if !asked || err != nil {
		return true, err
	}
	at, err := now()
	if err != nil {
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
	spent := math.Inf(1) // a meter that cannot be read is past any cap, and is kept as it is
	if read {
		ledger = moved(ledger, listed, at, prices)
		spent, _ = ledger.Num("spent")
	}
	sshKey()
	var late []any
	for _, machine := range listed {
		why := ""
		switch {
		case at >= machine.Until:
			why = "past its end"
		case len(prices) == 0:
			why = "with no price kept"
		case spent > cap:
			why = "past the cap"
		case len(work) == 0: // none listed has an address: each is still starting
			why = "no work marked"
		default:
			continue
		}
		said := machine.Name + " listed " + why + ", given back"
		if err := GiveBack(machine); err != nil {
			said = machine.Name + " listed " + why + ", not given back: " + err.Error()
		}
		late = append(late, said)
	}
	// no machine to reach: the routes are ssh's own config alone
	err = save(routesPath(), "Host *\n  Include ~/.ssh/config\n")
	if err == nil {
		err = save(filepath.Join(config.Home(), "state", "google-cloud-late.json"), run.Encode(late)+"\n")
	}
	if err == nil && read {
		err = save(meterPath(), run.Encode(ledger)+"\n")
	}
	if err != nil || !renting {
		return true, err
	}
	if !possible(keptAt) || at-keptAt >= freshFor || slices.ContainsFunc(offered, func(o Offer) bool { return len(o.Zones) == 0 }) {
		if offered, err = Offers(); err == nil {
			err = Keep(offered)
		}
	}
	return true, err
}

// sshKey makes ak's ssh key where it is missing and forgets ssh-keygen's copy of the hosts it
// knew, as Python's google_cloud._idle does before it asks the machines it reaches, here none.
func sshKey() {
	path := filepath.Join(config.Home(), "secrets", "google-cloud-ssh")
	if _, err := os.Stat(path); err != nil && exec.Command("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "ak", "-f", path).Run() != nil {
		return
	}
	os.Remove(filepath.Join(config.Home(), "secrets", "google-cloud-known-hosts.old"))
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
