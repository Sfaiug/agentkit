package config

import (
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strings"
)

type namedModel struct {
	name  string
	entry *table
}

// ModelTicks keeps removed entries for this visit. Edits start from the file, so loaded
// defaults never turn into written ones; returning to its original contents restores its bytes.
type ModelTicks struct {
	Harnesses      []string
	root, original *table
	text           []byte
	canonical      string
	providers      map[string]string
	gone           map[[2]string][]namedModel
}

func OpenModelTicks() (*ModelTicks, error) {
	data, root, err := modelFile()
	if err != nil {
		return nil, err
	}
	ticks := &ModelTicks{root: root, original: root, text: data,
		providers: map[string]string{}, gone: map[[2]string][]namedModel{}}
	if ticks.canonical, err = dump(root); err != nil {
		return nil, err
	}
	shipped, _ := parseDocument(defaultConfig)
	providers := root.get("providers").(*table)
	for _, name := range present(shipped.get("models").(*table)) {
		entry := shipped.get("models").(*table).get(name).(*table)
		harness, _ := entry.get("harness").(string)
		provider, _ := entry.get("provider").(string)
		if providers.get(provider) != nil && ticks.providers[harness] == "" {
			ticks.providers[harness] = provider
		}
	}
	for _, provider := range present(providers) {
		for _, doc := range []*table{root, shipped} {
			models := doc.get("models").(*table)
			for _, name := range present(models) {
				entry, _ := models.get(name).(*table)
				harness, ok := entry.get("harness").(string)
				if ok && entry.get("provider") == provider {
					if !slices.Contains(ticks.Harnesses, harness) {
						ticks.Harnesses = append(ticks.Harnesses, harness)
					}
					if ticks.providers[harness] == "" {
						ticks.providers[harness] = provider
					}
				}
			}
		}
	}
	return ticks, nil
}

func modelFile() ([]byte, *table, error) {
	data, err := os.ReadFile(filepath.Join(Home(), "config.toml"))
	if err != nil && !os.IsNotExist(err) {
		return nil, nil, err
	}
	root, err := parseDocument(string(data))
	if err != nil {
		return nil, nil, err
	}
	if !hasTables(root) {
		root, err = load()
		if err != nil {
			return nil, nil, err
		}
	}
	for _, key := range []string{"models", "providers"} {
		if _, ok := root.get(key).(*table); !ok {
			return nil, nil, fmt.Errorf("missing [%s] table", key)
		}
	}
	return data, root, err
}

func modelMatches(root *table, harness, id string) []string {
	var names []string
	for _, name := range offered(root) {
		entry := root.get("models").(*table).get(name).(*table)
		if entry.get("harness") == harness && (id == "" || entry.get("model") == id) {
			names = append(names, name)
		}
	}
	return names
}

func (t *ModelTicks) Names(harness, id string) []string { return modelMatches(t.root, harness, id) }

func (t *ModelTicks) Tick(harness, id, label string, levels []string, keep func() error) error {
	_, root, err := modelFile()
	if err != nil {
		return err
	}
	models, providers := root.get("models").(*table), root.get("providers").(*table)
	key, names := [2]string{harness, id}, modelMatches(root, harness, id)
	removed := []namedModel{}
	if len(names) > 0 {
		if len(names) == len(offered(root)) {
			return fmt.Errorf("the config needs one model")
		}
		for _, name := range names {
			entry := models.get(name).(*table)
			removed = append(removed, namedModel{name, entry})
			delete(models.values, name)
		}
		pruned := []string{}
		for _, one := range removed {
			// A model added here had no settings to clean up when this page opened.
			if t.original.get("models").(*table).get(one.name) == nil {
				continue
			}
			pruned = append(pruned, one.name)
			provider, _ := one.entry.get("provider").(string)
			entry, _ := providers.get(provider).(*table)
			if entry.get("usage_model") == one.name {
				delete(entry.values, "usage_model")
			}
			if entry.get("mode") == "free" && !slices.ContainsFunc(offered(root), func(name string) bool {
				return models.get(name).(*table).get("provider") == provider
			}) {
				delete(providers.values, provider)
			}
		}
		if len(pruned) > 0 {
			pruneModelDefaults(root, pruned)
		}
	} else {
		entries := t.gone[key]
		if len(entries) == 0 {
			if len(levels) == 0 {
				return fmt.Errorf("the model lists no efforts")
			}
			provider, effort := t.providers[harness], "high"
			if on := modelMatches(root, harness, ""); len(on) > 0 {
				first := models.get(on[0]).(*table)
				provider, _ = first.get("provider").(string)
				effort, _ = first.get("effort").(string)
			}
			entry := newTable()
			entry.put("harness", harness)
			entry.put("model", id)
			entry.put("effort", nearestEffort(effort, levels))
			entry.put("provider", provider)
			entries = []namedModel{{t.shortName(models, label), entry}}
		}
		for _, entry := range entries {
			if models.get(entry.name) != nil {
				return fmt.Errorf("model %s is already configured", entry.name)
			}
			models.put(entry.name, entry.entry)
			provider, _ := entry.entry.get("provider").(string)
			if providers.get(provider) == nil {
				providers.put(provider, t.original.get("providers").(*table).get(provider))
			}
		}
	}
	text, err := dump(root)
	if err != nil {
		return err
	}
	if text == t.canonical {
		text = string(t.text)
	}
	if err := keep(); err != nil {
		return err
	}
	path := filepath.Join(Home(), "config.toml")
	tmp := filepath.Join(Home(), "config.tmp")
	if err := os.WriteFile(tmp, []byte(text), 0o600); err != nil {
		return err
	}
	if err := os.Chmod(tmp, 0o600); err != nil {
		return err
	}
	if err := os.Rename(tmp, path); err != nil {
		return err
	}
	t.root = root
	if len(removed) > 0 {
		t.gone[key] = removed
	}
	return nil
}

// Only explicitly written defaults that name a removed model need pruning.
func pruneModelDefaults(root *table, removed []string) {
	defaults, ok := root.get("defaults").(*table)
	if !ok {
		return
	}
	names := offered(root)
	if name, set := defaults.get("orchestrator").(string); set && slices.Contains(removed, name) {
		defaults.put("orchestrator", names[0])
	}
	for _, key := range []string{"workers", "reviewers"} {
		if group, set := defaults.get(key).([]any); set {
			kept := slices.DeleteFunc(slices.Clone(group), func(name any) bool { return slices.Contains(removed, name.(string)) })
			if len(group) > 0 && len(kept) == 0 {
				kept = []any{names[0]}
			}
			defaults.put(key, kept)
		}
	}
}

var modelWords = regexp.MustCompile(`[a-z0-9]+`)

func (t *ModelTicks) shortName(models *table, label string) string {
	words := []string{}
	for _, word := range modelWords.FindAllString(strings.ToLower(strings.ReplaceAll(label, "'", "")), -1) {
		if !strings.ContainsAny(word, "0123456789") && !slices.Contains(words, word) {
			words = append(words, word)
		}
	}
	base := strings.Join(words, "-")
	if base == "" {
		base = "model"
	}
	taken := func(name string) bool {
		for _, entries := range t.gone {
			if slices.ContainsFunc(entries, func(one namedModel) bool { return one.name == name }) {
				return true
			}
		}
		return models.get(name) != nil
	}
	name := base
	for n := 2; taken(name); n++ {
		name = fmt.Sprintf("%s-%d", base, n)
	}
	return name
}

func nearestEffort(word string, levels []string) string {
	if slices.Contains(levels, word) {
		return word
	}
	rankings := slices.Concat([]string{"none", "minimal"}, fixedEfforts)
	at, nearest, distance := slices.Index(rankings, word), levels[0], len(rankings)
	if at < 0 {
		return nearest
	}
	for _, level := range levels {
		if rank := slices.Index(rankings, level); rank >= 0 && absRank(rank-at) < distance {
			nearest, distance = level, absRank(rank-at)
		}
	}
	return nearest
}

func absRank(n int) int { return max(n, -n) }
