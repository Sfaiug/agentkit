package harness

// Company is a provider's own name and colour on every screen, Python's menu.NAMES and
// menu.COLOURS: "" for one shipped with neither, which a provider's own `name` and `colour` keys
// override anyway.
func Company(provider string) (name, colour string) {
	return map[string]string{"anthropic": "Claude", "openai": "ChatGPT", "meta": "Muse", "xai": "Grok", "google": "Gemini", "mimo": "MiMo"}[provider],
		map[string]string{"anthropic": "#D97757", "openai": "#FFFFFF", "meta": "#3E9EFB", "xai": "#736CD3", "google": "#203B9B", "mimo": "#FB8046"}[provider]
}

// Heading is the company a shipped provider's subscriptions sit under on Subscriptions, Python's
// menu.COMPANIES without the harness each runs on: "" for one shipped with none, headed by its name.
func Heading(provider string) string {
	return map[string]string{"anthropic": "Anthropic", "openai": "OpenAI", "meta": "Meta", "xai": "xAI", "google": "Google"}[provider]
}
