package harness

import (
	"cmp"
	"strings"
	"unicode"
)

// Company is a provider's own name and colour on every screen and page, Python's
// menu.NAMES.get(provider, provider.title()) and menu.COLOURS: a provider shipped with no name is
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
