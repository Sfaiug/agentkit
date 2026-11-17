package harness

import (
	"cmp"
	"unicode"

	"agentkit/internal/config"
)

// SubscriptionName is what a person reads for one of a provider's subscriptions wherever ak names
// it, a screen, `ak usage` or a page, Python's config.account_label: the provider's name, and for
// one of several its place among them in roman numerals, `Claude II`; the account "" is the
// provider's one login.
func SubscriptionName(provider, account string) (string, error) {
	name, err := ProviderName(provider)
	if err != nil {
		return name, err
	}
	listed, err := config.Accounts(provider)
	return config.AccountLabel(listed, account, name), err
}

// ProviderName is a provider's name on every screen, Python's config.provider_name: its own `name`,
// else its Company's.
func ProviderName(provider string) (string, error) {
	own, err := config.ProviderName(provider)
	return cmp.Or(own, Company(provider)), err
}

// Company is a provider's own name on every screen and page, Python's
// config.NAMES.get(provider, provider.title()): a provider shipped with no name is its key
// capitalised, which a provider's own `name` key overrides anyway.
func Company(provider string) string {
	return cmp.Or(map[string]string{"anthropic": "Claude", "openai": "ChatGPT", "meta": "Muse", "xai": "Grok", "google": "Gemini", "mimo": "MiMo"}[provider], capitalised(provider))
}

// capitalised is a provider's key capitalised as Python's str.title does.
func capitalised(name string) string {
	out, start := []rune(name), true
	for i, r := range out {
		if start {
			out[i] = unicode.ToUpper(r)
		} else {
			out[i] = unicode.ToLower(r)
		}
		start = !unicode.IsLetter(r)
	}
	return string(out)
}

// Heading is what provider's subscriptions sit under, bold, on Subscriptions and on `+ add a
// subscription` alike, Python's menu.company_name: its company where it is shipped with one
// (menu.COMPANIES), else name, its own.
func Heading(provider, name string) string {
	return cmp.Or(map[string]string{"anthropic": "Anthropic", "openai": "OpenAI", "meta": "Meta", "xai": "xAI",
		"google": "Google"}[provider], name)
}
