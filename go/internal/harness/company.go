package harness

import (
	"cmp"
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

// Heading is the company a shipped provider's subscriptions sit under on Subscriptions, Python's
// menu.COMPANIES without the harness each runs on: "" for one shipped with none, headed by its name.
func Heading(provider string) string {
	return map[string]string{"anthropic": "Anthropic", "openai": "OpenAI", "meta": "Meta", "xai": "xAI", "google": "Google"}[provider]
}
