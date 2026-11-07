package usage

import "agentkit/internal/config"

// TurnAccount is the login a worker turn on that provider runs on, Python's usage.account, which
// the launch, the resume and each turn ask: "" for a provider listing none, its one login; the one
// it lists; ErrPython where it lists several, among which Python's turn picks by their meters.
func TurnAccount(provider string) (string, error) {
	accounts, err := config.Accounts(provider)
	switch {
	case err != nil:
		return "", err
	case len(accounts) > 1:
		return "", ErrPython
	case len(accounts) == 1:
		return accounts[0], nil
	}
	return "", nil
}
