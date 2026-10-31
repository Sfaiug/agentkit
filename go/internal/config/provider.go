package config

// Accounts are the subscriptions a provider lists, in the order they are tried, as Python's
// config.accounts reads them: none for one that lists none, which is one login.
func Accounts(provider string) ([]string, error) {
	root, err := load()
	if err != nil {
		return nil, err
	}
	providers, _ := root.get("providers").(*table)
	return words(providers, provider, "accounts"), nil
}
