package config

import (
	"slices"
	"strings"
)

// ProviderName is what a provider's table names it on a screen: its own `name`, stripped; "" where
// it names none.
func ProviderName(provider string) (string, error) {
	root, err := load()
	if err != nil {
		return "", err
	}
	providers, _ := root.get("providers").(*table)
	entry, _ := providers.get(provider).(*table)
	name, _ := entry.get("name").(string)
	return strings.TrimSpace(name), nil
}

const (
	TokenLife = 365 // days a worker token lives from its file's date (watch.TOKEN_LIFE_DAYS)
	TokenWarn = 14  // days out the ak screen says it (watch.TOKEN_WARN_DAYS)
)

// WorkerTokens is {harness, its token's file name, how to renew it} for each harness declaring a
// worker token and its remedy, by harness name (watch.token_files).
func WorkerTokens() ([][3]string, error) {
	found, err := manifests()
	if err != nil {
		return nil, err
	}
	var tokens [][3]string
	for harness, manifest := range found {
		block, _ := manifest.values["worker_token"].(*table)
		file, _ := block.get("file").(string)
		remedy, _ := block.get("remedy").(string)
		if file != "" && file != "." && file != ".." && !strings.Contains(file, "/") && remedy != "" {
			tokens = append(tokens, [3]string{harness, file, remedy})
		}
	}
	slices.SortFunc(tokens, func(a, b [3]string) int { return strings.Compare(a[0], b[0]) })
	return tokens, nil
}
