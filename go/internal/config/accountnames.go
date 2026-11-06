package config

import (
	"slices"
	"strings"
)

// AccountLabel is what a person reads for one of a provider's subscriptions, Python's
// config.account_label: name, and for one of several listed its place among them in roman
// numerals, `acme II`; one no longer listed keeps its own name, as no place says which it is.
func AccountLabel(listed []string, account, name string) string {
	at := slices.Index(listed, account)
	switch {
	case at < 0 && (account == "" || account == DefaultAccount):
		return name
	case at < 0:
		return name + " " + account
	case len(listed) < 2:
		return name
	}
	number, numeral := at+1, ""
	for _, step := range []struct {
		value  int
		digits string
	}{{1000, "M"}, {900, "CM"}, {500, "D"}, {400, "CD"}, {100, "C"}, {90, "XC"}, {50, "L"}, {40, "XL"}, {10, "X"}, {9, "IX"}, {5, "V"}, {4, "IV"}, {1, "I"}} {
		numeral += strings.Repeat(step.digits, number/step.value)
		number %= step.value
	}
	return name + " " + numeral
}

// SeatAccount is the account a new seat on that provider opens on first while it has room: its
// `seat_account`, else the usual login.
func SeatAccount(provider string) (string, error) {
	root, err := load()
	if err != nil {
		return "", err
	}
	providers, _ := root.get("providers").(*table)
	entry, _ := providers.get(provider).(*table)
	if named, ok := entry.get("seat_account").(string); ok {
		return named, nil
	}
	return DefaultAccount, nil
}
