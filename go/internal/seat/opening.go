package seat

import (
	"fmt"
	"slices"

	"agentkit/internal/adapters"
	"agentkit/internal/config"
	usages "agentkit/internal/usage"
)

// OpeningAccount is the account a new seat of that model opens on, Python's orch.opening_account:
// the first its seat login passes of the provider's accounts as the meters rank them for it, its
// `seat_account` first while that has room, else the usual login where listed, for its owner to
// sign in on; "" for a provider of one login.
func OpeningAccount(name string, model config.Model) (string, error) {
	listed, err := config.Accounts(model.Provider)
	if err != nil || len(listed) == 0 {
		return "", err
	}
	home, err := config.SeatAccount(model.Provider)
	if err != nil {
		return "", err
	}
	readings, err := usages.Read()
	if err != nil {
		return "", err
	}
	ranked, err := readings.Accounts(name, home)
	if err != nil {
		return "", err
	}
	var order []string
	for _, account := range ranked {
		order = append(order, account.Name)
	}
	for _, account := range listed {
		if !slices.Contains(order, account) {
			order = append(order, account)
		}
	}
	for _, account := range order {
		if adapters.SeatAuth(model.Harness, account) {
			return account, nil
		}
	}
	if slices.Contains(listed, config.DefaultAccount) {
		return config.DefaultAccount, nil
	}
	return "", fmt.Errorf("%s: no account has a working seat login", model.Provider)
}
