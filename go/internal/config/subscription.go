package config

import (
	"math"
	"math/big"
)

// A Subscription is a [providers.*] table load keeps, as the usage read and the pick read it:
// how it is paid (`mode`) and its price a month (`price`), where it names them, and Via, the
// first [models.*] entry naming it, whose harness's adapter answers for its meters, as Python's
// config.provider_harness finds it; Via "" where no entry names it.
type Subscription struct {
	Name, Mode, Harness, Via string
	Price                    *float64
}

// Subscriptions is every Subscription, in the order the file names them.
func Subscriptions() ([]Subscription, error) {
	root, err := load()
	if err != nil {
		return nil, err
	}
	providers, models := root.values["providers"].(*table), root.values["models"].(*table)
	var found []Subscription
	for _, name := range providers.keys {
		value, kept := providers.values[name]
		if !kept { // a bare free provider load drops
			continue
		}
		entry, _ := value.(*table)
		sub := Subscription{Name: name}
		sub.Mode, _ = entry.get("mode").(string)
		if price, ok := tomlNumber(entry.get("price")); ok {
			sub.Price = &price
		}
		for _, model := range models.keys {
			if each, _ := models.values[model].(*table); each.get("provider") == name {
				sub.Harness, _ = each.get("harness").(string)
				sub.Via = model
				break
			}
		}
		found = append(found, sub)
	}
	return found, nil
}

// UsageFacts is a harness's `[usage]` table as Python's harness plugin reads it: whether its probe
// runs a model (`capture`), its answer says no time (`strips_timestamp`), it counts usage-limit
// resets (`reset`) or it reads no meter at all (`none`), and how often its endpoint may be asked,
// in seconds, 0 where it names no number.
type UsageFacts struct {
	Capture, StripsTimestamp, Reset, None bool
	ProbeEvery                            float64
}

// Usage is that harness's UsageFacts.
func Usage(harness string) (UsageFacts, error) {
	section, err := Section(harness, "usage")
	every, _ := tomlNumber(section["probe_every"])
	return UsageFacts{truthy(section["capture"]), truthy(section["strips_timestamp"]), truthy(section["reset"]),
		truthy(section["none"]), every}, err
}

// PaceMargin is the config's `pace_margin`, written at the top or, in an older file, under
// [tiers], ten where neither names one; false where Python's usage.margin refuses it: anything
// but a number from 0 up to 100.
func PaceMargin() (float64, bool) {
	root, err := load()
	if err != nil {
		return 0, false
	}
	value, set := root.values["pace_margin"]
	if tiers, ok := root.values["tiers"].(*table); !set && ok {
		value, set = tiers.values["pace_margin"]
	}
	if !set {
		return 10, true
	}
	margin, ok := tomlNumber(value)
	return margin, ok && margin >= 0 && margin < 100
}

// tomlNumber is a TOML number as Python's float() makes it, false for anything else or one past a
// float's range.
func tomlNumber(value any) (float64, bool) {
	switch value := value.(type) {
	case *big.Int:
		float, _ := new(big.Float).SetInt(value).Float64()
		return float, !math.IsInf(float, 0)
	case float64:
		return value, !math.IsInf(value, 0) && !math.IsNaN(value)
	}
	return 0, false
}

// truthy is whether Python reads a TOML value as true.
func truthy(value any) bool {
	switch value := value.(type) {
	case bool:
		return value
	case string:
		return value != ""
	case *big.Int:
		return value.Sign() != 0
	case float64:
		return value != 0
	case []any:
		return len(value) > 0
	case *table:
		return len(value.values) > 0
	case tableArray:
		return len(value) > 0
	}
	return value != nil
}
