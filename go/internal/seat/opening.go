package seat

import (
	"fmt"
	"slices"

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
	readings, err := usages.Collected()
	if err != nil {
		return "", err
	}
	ranked, err := readings.Accounts(name, home)
	if err != nil {
		return "", err
	}
	if account := workingAccount(model.Harness, ranked, listed); account != "" {
		return account, nil
	}
	if slices.Contains(listed, config.DefaultAccount) {
		return config.DefaultAccount, nil
	}
	return "", fmt.Errorf("%s: no account has a working seat login", model.Provider)
}
