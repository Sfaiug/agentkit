package config

import "strings"

// Company is the provider named by a board's maker: an explicit mapping in the
// home config wins over the shipped one, else the maker's name in lower case.
func Company(maker string) (string, error) {
	root, err := load()
	if err != nil {
		return "", err
	}
	shipped, err := parseDocument(defaultConfig)
	if err != nil {
		return "", err
	}
	for _, source := range []*table{root, shipped} {
		providers, _ := source.get("providers").(*table)
		for _, name := range providers.keys {
			entry, _ := providers.get(name).(*table)
			if entry.get("maker") == maker {
				return name, nil
			}
		}
	}
	return strings.ToLower(maker), nil
}
