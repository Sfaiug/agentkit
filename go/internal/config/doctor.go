package config

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"
)

// OfferedHarnesses is each harness of a model the config offers, once, or why the config is
// refused, as Python's config.load says it.
func OfferedHarnesses() ([]string, error) {
	root, err := load()
	if err != nil {
		return nil, err
	}
	var harnesses []string
	for _, name := range offered(root) {
		harness := root.values["models"].(*table).values[name].(*table).values["harness"].(string)
		if !slices.Contains(harnesses, harness) {
			harnesses = append(harnesses, harness)
		}
	}
	return harnesses, nil
}

// Lister is the script to ask for that harness's models, as Python's config.adapter_path finds
// it: $AGENTKIT_ADAPTER_DIR's, "" where none runs there, which lists nothing, else the checkout's.
// False where there is none to ask: go/adapters' stubs carry out no `models`, and a shipped
// adapter answers only beside the tools/catalog.py it prints the table with.
func Lister(harness string) (string, bool) {
	script, err := Adapter(harness)
	if !errors.Is(err, ErrNoAdapterDir) {
		return script, true
	}
	repo := Repo()
	script = filepath.Join(repo, "adapters", harness+".sh")
	_, runs := exec.LookPath(script)
	_, table := os.Stat(filepath.Join(repo, "tools", "catalog.py"))
	return script, runs == nil && table == nil
}

// ListingLogins is what the adapter is told on each login a question about that harness's models
// goes to, as Python's config._logins picks them: every subscription of each provider a model of
// the config, or else of the shipped one, runs there; the usual login alone where the harness
// keeps one, or none of those is left.
func ListingLogins(harness string) ([][]string, error) {
	root, err := load()
	if err != nil {
		return nil, err
	}
	manifests, err := manifests()
	if err != nil {
		return nil, err
	}
	auth, _ := manifests[harness].get("auth").(*table)
	var accounts []string
	on := map[string][]string{}
	if auth.get("accounts") != false {
		shipped, _ := parseDocument(defaultConfig)
		runs := map[string]bool{}
		for _, doc := range []*table{root, shipped} {
			models, _ := doc.get("models").(*table)
			if models == nil {
				continue
			}
			for _, value := range models.values {
				entry, _ := value.(*table)
				if provider, ok := entry.get("provider").(string); ok && entry.get("harness") == harness {
					runs[provider] = true
				}
			}
		}
		providers := root.values["providers"].(*table)
		for _, provider := range providers.keys {
			if !runs[provider] {
				continue
			}
			listed := words(providers, provider, "accounts")
			if len(listed) == 0 {
				listed = []string{""}
			}
			for _, account := range listed {
				if account == "default" {
					account = ""
				}
				if _, seen := on[account]; !seen {
					accounts = append(accounts, account)
				}
				on[account] = append(on[account], provider)
			}
		}
	}
	if len(accounts) == 0 {
		accounts = []string{""}
	}
	var told [][]string
	for _, account := range accounts {
		told = append(told, []string{"AGENTKIT_ACCOUNT=" + account, "AGENTKIT_PROVIDER=" + strings.Join(on[account], " ")})
	}
	return told, nil
}

// WrongEfforts is a line for each effort an offered model is set to and does not take, as Python's
// watch.doctor words it: `effort` always, a role's where the entry sets it. What a model takes is
// listed's answer, in config.efforts' order, else Efforts'.
func WrongEfforts(listed func(harness, model string) []string) ([]string, error) {
	root, err := load()
	if err != nil {
		return nil, err
	}
	var wrong []string
	for _, name := range offered(root) {
		entry := root.values["models"].(*table).values[name].(*table)
		harness := entry.values["harness"].(string)
		model, _ := entry.values["model"].(string)
		takes := listed(harness, model)
		if len(takes) == 0 {
			if takes, err = Efforts(harness, model); err != nil {
				return nil, err
			}
		}
		for _, key := range RoleEfforts {
			value, set := entry.values[key]
			if word, isWord := value.(string); (key == "effort" || set) && !(isWord && slices.Contains(takes, word)) {
				wrong = append(wrong, fmt.Sprintf("%s  %s: %s takes %s, not %s", key, name, shown(entry.values["model"]), strings.Join(takes, " "), shown(value)))
			}
		}
	}
	return wrong, nil
}

// shown is a TOML value as Python's str() writes it, one left out being None.
func shown(value any) string {
	switch value := value.(type) {
	case nil:
		return "None"
	case string:
		return value
	}
	return valueRepr(value)
}

// MachineNames is what config.toml itself names of the machines ak may use, as Python's
// machines.helpers reads it, not load's: `[machines.<ssh alias>]`, then `suite_helper`.
func MachineNames() []string {
	var names []string
	value, _, _ := topLevel("machines")
	if machines, ok := value.(*table); ok {
		names = slices.Clone(machines.keys)
	}
	value, _, _ = topLevel("suite_helper")
	if helper, ok := value.(string); ok && helper != "" {
		names = append(names, helper)
	}
	return names
}
