package harness

import (
	"cmp"
	"strings"
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
	own, _, err := config.ProviderLook(provider)
	company, _ := Company(provider)
	return cmp.Or(own, company), err
}

// Company is a provider's own name and colour on every screen and page, Python's
// config.NAMES.get(provider, provider.title()) and menu.COLOURS: a provider shipped with no name is
// its key capitalised, and one with no colour "", which a provider's own `name` and `colour` keys
// override anyway.
func Company(provider string) (name, colour string) {
	return cmp.Or(map[string]string{"anthropic": "Claude", "openai": "ChatGPT", "meta": "Muse", "xai": "Grok", "google": "Gemini", "mimo": "MiMo"}[provider], capitalised(provider)),
		map[string]string{"anthropic": "#D97757", "openai": "#FFFFFF", "meta": "#3E9EFB", "xai": "#736CD3", "google": "#203B9B", "mimo": "#FB8046"}[provider]
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

// Maker is the company a shipped provider is and the harness it runs on, as `+ add a subscription`
// offers it, Python's menu.COMPANIES: "" for one shipped with none.
func Maker(provider string) string {
	return map[string]string{"anthropic": "Anthropic / Claude Code", "openai": "OpenAI / Codex", "meta": "Meta / Muse",
		"xai": "xAI / Grok Build", "google": "Google / Antigravity"}[provider]
}

// Heading is the company a shipped provider's subscriptions sit under on Subscriptions, its Maker
// without the harness: "" for one shipped with none, headed by its name.
func Heading(provider string) string {
	company, _, _ := strings.Cut(Maker(provider), " / ")
	return company
}
