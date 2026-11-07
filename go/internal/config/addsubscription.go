package config

import (
	"cmp"
	"fmt"
	"slices"
	"strings"
)

// What `+ add a subscription` and `− remove` on `c` → Subscriptions read of the config and write to
// it (menu.config_add_provider, menu.config_remove_provider), each write saved as `c` saves.

// ProviderHosts is each harness that runs any provider it can log in to, by name, and the label its
// manifest's `[providers] label` gives it (config.provider_hosts).
func ProviderHosts() (harnesses []string, labels map[string]string) {
	found, _ := manifests()
	labels = map[string]string{}
	for harness, manifest := range found {
		block, _ := manifest.get("providers").(*table)
		if label, ok := block.get("label").(string); ok {
			harnesses, labels[harness] = append(harnesses, harness), label
		}
	}
	slices.Sort(harnesses)
	return harnesses, labels
}

// OneLogin is whether that harness keeps one login for each provider, as its manifest's `[auth]
// accounts = false` says: no other subscription of a provider can be logged in on it.
func OneLogin(harness string) bool {
	auth, _ := Section(harness, "auth")
	return auth["accounts"] == false
}

// ProviderNames is the providers the config has, in its order, and the ones the shipped default has
// and it lacks, in the shipped order.
func ProviderNames() (has, lacks []string, err error) {
	root, err := load()
	if err != nil {
		return nil, nil, err
	}
	has = present(root.get("providers").(*table))
	shipped, _ := parseDocument(defaultConfig)
	providers, _ := shipped.get("providers").(*table)
	for _, name := range present(providers) {
		if !slices.Contains(has, name) {
			lacks = append(lacks, name)
		}
	}
	return has, lacks, nil
}

// ProviderHarnesses is the harnesses that provider runs on: its models' in the config, then the
// shipped default's, each once (config.provider_harnesses).
func ProviderHarnesses(provider string) ([]string, error) {
	root, err := load()
	if err != nil {
		return nil, err
	}
	shipped, _ := parseDocument(defaultConfig)
	return harnessesOf(provider, root, shipped), nil
}

// ShippedHarnesses is the harnesses the shipped default runs that provider's models on, each once.
func ShippedHarnesses(provider string) []string {
	shipped, _ := parseDocument(defaultConfig)
	return harnessesOf(provider, shipped)
}

// harnessesOf is the harnesses the models of docs, in their order, run that provider's models on.
func harnessesOf(provider string, docs ...*table) []string {
	var harnesses []string
	for _, doc := range docs {
		models, _ := doc.get("models").(*table)
		for _, name := range present(models) {
			entry, _ := models.get(name).(*table)
			if harness, ok := entry.get("harness").(string); ok && entry.get("provider") == provider && !slices.Contains(harnesses, harness) {
				harnesses = append(harnesses, harness)
			}
		}
	}
	return harnesses
}

// ShippedModel is the shipped default's first model of that provider: its harness and its name
// (config.provider_harness of the shipped default).
func ShippedModel(provider string) (harness, name string, err error) {
	shipped, _ := parseDocument(defaultConfig)
	models, _ := shipped.get("models").(*table)
	for _, name := range present(models) {
		entry, _ := models.get(name).(*table)
		if harness, ok := entry.get("harness").(string); ok && entry.get("provider") == provider {
			return harness, name, nil
		}
	}
	return "", "", fmt.Errorf("~/.agentkit/config.toml: [providers.%s] has no model", provider)
}

// HasModel is whether the config has a model of that name.
func HasModel(name string) (bool, error) {
	root, err := load()
	if err != nil {
		return false, err
	}
	return root.get("models").(*table).get(name) != nil, nil
}

// AddProvider puts provider in the config as the shipped default has it, listing account alone,
// with the shipped default's first model of it (ShippedModel) on its harness's id, at the effort the
// shipped default gives it or the nearest of levels.
func AddProvider(provider, account, id string, levels []string, keep func() error) error {
	harness, name, err := ShippedModel(provider)
	if err != nil {
		return err
	}
	return saveSubscriptions(func(root *table) error {
		shipped, _ := parseDocument(defaultConfig)
		entry, _ := shipped.get("providers").(*table).get(provider).(*table)
		entry.put("accounts", listed([]string{account}))
		root.get("providers").(*table).put(provider, entry)
		effort, _ := shipped.get("models").(*table).get(name).(*table).get("effort").(string)
		root.get("models").(*table).put(name, modelEntry(harness, id, nearestEffort(effort, levels), provider))
		return nil
	}, keep)
}

// ListAccounts makes accounts provider's `accounts`.
func ListAccounts(provider string, accounts []string, keep func() error) error {
	return saveSubscriptions(func(root *table) error {
		entry, err := providerTable(root, provider)
		if err == nil {
			entry.put("accounts", listed(accounts))
		}
		return err
	}, keep)
}

// Runs is the names the config runs that harness's model under, at effort where one is named
// (menu._runs).
func Runs(harness, id, effort string) ([]string, error) {
	root, err := load()
	if err != nil {
		return nil, err
	}
	models, names := root.get("models").(*table), []string{}
	for _, name := range present(models) {
		entry, _ := models.get(name).(*table)
		if entry.get("harness") == harness && entry.get("model") == id && (effort == "" || entry.get("effort") == effort) {
			names = append(names, name)
		}
	}
	return names, nil
}

// TakeIn puts a model a host harness runs in the config, named from its label as Models names one,
// under a provider the harness lists (takeIn).
func TakeIn(model, harness, id, effort, provider, label, mode string, keep func() error) error {
	return saveSubscriptions(func(root *table) error {
		name := (&ModelTicks{}).shortName(root.get("models").(*table), model)
		entry := modelEntry(harness, id, effort, provider)
		takeIn(root.get("providers").(*table), entry, Listed{provider, label, mode})
		root.get("models").(*table).put(name, entry)
		return nil
	}, keep)
}

// takeIn gives a model entry under a provider a host lists that provider's table where providers have
// none: the shipped default's where it has one, else the listed mode under the listed name.  The
// entry takes that mode as its own where its provider's table says another (menu._take_in).
func takeIn(providers, entry *table, under Listed) {
	if providers.get(under.ID) == nil {
		shipped, _ := parseDocument(defaultConfig)
		fresh, ok := shipped.get("providers").(*table).get(under.ID).(*table)
		if !ok {
			fresh = newTable()
			fresh.put("mode", under.Mode)
			fresh.put("name", under.Name)
		}
		providers.put(under.ID, fresh)
	}
	// a table that came with another harness's login: a plan paid for there pays for no call a host
	// makes on that provider's key
	if own, _ := providers.get(under.ID).(*table).get("mode").(string); under.Mode != cmp.Or(own, "subscription") {
		entry.put("mode", under.Mode)
	}
}

// RemoveProvider takes provider out of the config, its table and its models, [defaults] passing over
// them; the last provider with a model cannot go (config.remove_provider).
func RemoveProvider(provider string, keep func() error) error {
	return saveSubscriptions(func(root *table) error {
		if _, err := providerTable(root, provider); err != nil {
			return err
		}
		models := root.get("models").(*table)
		if !slices.ContainsFunc(offered(root), func(name string) bool { return models.get(name).(*table).get("provider") != provider }) {
			return fmt.Errorf("%s is the last provider with a model; add another before removing it", provider)
		}
		delete(root.get("providers").(*table).values, provider)
		var gone []string
		for _, name := range present(models) {
			if entry, _ := models.get(name).(*table); entry.get("provider") == provider {
				gone = append(gone, name)
				delete(models.values, name)
			}
		}
		pruneModelDefaults(root, gone)
		return nil
	}, keep)
}

// saveSubscriptions is the config with change made to it, saved as `c` saves.
func saveSubscriptions(change func(root *table) error, keep func() error) error {
	return saveConfig(modelTable, change, keep)
}

func providerTable(root *table, provider string) (*table, error) {
	providers := root.get("providers").(*table)
	if entry, ok := providers.get(provider).(*table); ok {
		return entry, nil
	}
	return nil, fmt.Errorf("no provider %q; the config has %s", provider, strings.Join(present(providers), ", "))
}

func modelEntry(harness, id, effort, provider string) *table {
	entry := newTable()
	entry.put("harness", harness)
	entry.put("model", id)
	entry.put("effort", effort)
	entry.put("provider", provider)
	return entry
}
