package googlecloud

import (
	"encoding/json"
	"math"
	"os"
	"path/filepath"
	"strings"

	"agentkit/internal/config"
)

// Keep is the tick keeping offered, at this package's time, in Python's google-cloud-offers.json:
// an object of `at` and `offers`, each offer its fields in order, written whole through its .tmp,
// which the tick's watch.tick.lock keeps to one writer.
func Keep(offered []Offer) error {
	at, err := now()
	if err != nil {
		return err
	}
	rows := make([][]any, len(offered))
	for n, o := range offered {
		zones := append([]string{}, o.Zones...) // a list, of none too
		rows[n] = []any{o.Name, o.Region, o.Cores, o.MemoryMB, o.Hourly, zones, o.Image, o.Disk}
	}
	data, err := json.MarshalIndent(map[string]any{"at": at, "offers": rows}, "", "  ")
	path := keptPath()
	if err == nil {
		err = os.MkdirAll(filepath.Dir(path), 0o700)
	}
	tmp := strings.TrimSuffix(path, ".json") + ".tmp"
	if err == nil {
		err = os.WriteFile(tmp, append(data, '\n'), 0o666)
	}
	if err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

// Kept is the offers the tick last kept and when, in Unix seconds, as Python's _kept: none at 0
// where it kept none ak can read or no `at`, NaN for an `at` that is no number, which possible
// refuses as _amount does. One kept before ak rented has only its first five fields.
func Kept() (float64, []Offer) {
	var kept struct {
		At     json.RawMessage
		Offers [][]json.RawMessage
	}
	data, err := os.ReadFile(keptPath())
	if err != nil || json.Unmarshal(data, &kept) != nil || kept.At == nil {
		return 0, nil
	}
	at := math.NaN()
	json.Unmarshal(kept.At, &at) // null, a string or a bool leaves it NaN
	offered := make([]Offer, len(kept.Offers))
	for n, fields := range kept.Offers {
		o := &offered[n]
		into := []any{&o.Name, &o.Region, &o.Cores, &o.MemoryMB, &o.Hourly, &o.Zones, &o.Image, &o.Disk}
		if len(fields) < 5 || len(fields) > len(into) {
			return 0, nil
		}
		for at, field := range fields {
			if json.Unmarshal(field, into[at]) != nil {
				return 0, nil
			}
		}
	}
	return at, offered
}

func keptPath() string { return filepath.Join(config.Home(), "state", "google-cloud-offers.json") }
