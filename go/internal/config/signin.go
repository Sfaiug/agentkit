package config

import "errors"

// DefaultAccount is the name a provider's usual login is listed under among its `accounts`.
const DefaultAccount = "default"

// AccountEnv is what an adapter call for that account is told: its name in AGENTKIT_ACCOUNT, and for
// the usual login, "" or DefaultAccount, the empty name the adapter takes as none (config.account_env).
func AccountEnv(account string) string {
	if account == DefaultAccount {
		account = ""
	}
	return "AGENTKIT_ACCOUNT=" + account
}

// LoginAdapter is the script that signs a harness's logins in and says when they end:
// $AGENTKIT_ADAPTER_DIR's, else the checkout's own, as Python's config.adapter finds it.
func LoginAdapter(harness string) (string, error) {
	adapter, err := Adapter(harness)
	if errors.Is(err, ErrNoAdapterDir) {
		return ShippedAdapter(harness)
	}
	return adapter, err
}

// SignsInAgain is whether that harness's adapter's `login again` signs that account in afresh: not
// its usual login, "" or DefaultAccount, where its manifest says `[auth] again = false`, as one that
// still stands cannot be signed in over (config.signs_in_again).
func SignsInAgain(harness, account string) bool {
	auth, _ := Section(harness, "auth")
	return account != "" && account != DefaultAccount || auth["again"] != false
}

// ShippedHarness is the first harness the shipped default runs that provider's models on, "" for
// none: what asks and signs in its logins once the config's models of it are all removed.
func ShippedHarness(provider string) string {
	shipped, _ := parseDocument(defaultConfig)
	models, _ := shipped.get("models").(*table)
	if models == nil {
		return ""
	}
	for _, name := range models.keys {
		if entry, _ := models.get(name).(*table); entry.get("provider") == provider {
			if harness, ok := entry.get("harness").(string); ok {
				return harness
			}
		}
	}
	return ""
}
