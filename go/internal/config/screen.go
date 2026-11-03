package config

import (
	"regexp"
	"slices"
	"strings"
)

var hexColour = regexp.MustCompile(`^#[0-9A-Fa-f]{6}$`)

// ProviderLook is what a provider's table says of how a screen shows it: its own `name`, stripped,
// and its own `colour`, where a valid one; "" for either it does not say.
func ProviderLook(provider string) (name, colour string, err error) {
	root, err := load()
	if err != nil {
		return "", "", err
	}
	providers, _ := root.get("providers").(*table)
	entry, _ := providers.get(provider).(*table)
	name, _ = entry.get("name").(string)
	colour, _ = entry.get("colour").(string)
	if !hexColour.MatchString(colour) {
		colour = ""
	}
	return strings.TrimSpace(name), colour, nil
}

// WorkerTokens is {harness, its token's file name} for each harness declaring a worker token and
// how to renew it, by harness name (watch.token_files).
func WorkerTokens() ([][2]string, error) {
	found, err := manifests()
	if err != nil {
		return nil, err
	}
	var tokens [][2]string
	for harness, manifest := range found {
		block, _ := manifest.values["worker_token"].(*table)
		file, _ := block.get("file").(string)
		remedy, _ := block.get("remedy").(string)
		if file != "" && file != "." && file != ".." && !strings.Contains(file, "/") && remedy != "" {
			tokens = append(tokens, [2]string{harness, file})
		}
	}
	slices.SortFunc(tokens, func(a, b [2]string) int { return strings.Compare(a[0], b[0]) })
	return tokens, nil
}
