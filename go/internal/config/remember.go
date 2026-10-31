package config

import (
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"slices"
	"strings"
)

// saveHeader opens the file Python's config.save writes.
var saveHeader = []string{"# agentkit's config, written by the menu's `c` screen. It is rewritten whole on every change,",
	"# so a comment left here would not survive it; unknown keys are kept as they are."}

// saveOrder is the keys Python's save writes first in the top level and in each known table,
// in its order; every other key follows in place.
var saveOrder = map[string][]string{
	"":          {"max_runs", "max_gates", "min_free_mb", "max_load", "run_memory_max_mb", "pace_margin", "within"},
	"defaults":  {"orchestrator", "workers", "reviewers"},
	"models":    {"harness", "model", "effort", "exec_effort", "review_effort", "provider", "meter", "mode"},
	"providers": {"mode", "usage_model", "usage_effort"},
}

// RememberDefaults is Python's config.remember_defaults of a new seat's models: what the next
// seat starts from, written as [defaults] into ~/.agentkit/config.toml where the file says
// otherwise.  The whole file is written as Python's save writes it: the config as load() reads
// it, the home file's own top-level keys over it.  Python's save first has every seat's record
// hold the efforts it runs at; Go's one caller opens a seat in a home with no other, whose
// record holds them already.  An error leaves the file as it was.
func RememberDefaults(orchestrator string, workers, reviewers []string) error {
	path := filepath.Join(Home(), "config.toml")
	data, err := os.ReadFile(path)
	if err != nil && !os.IsNotExist(err) {
		return err
	}
	file, err := parseDocument(string(data))
	if err != nil {
		return err
	}
	defaults := newTable()
	defaults.put("orchestrator", orchestrator)
	defaults.put("workers", listed(workers))
	if reviewers != nil {
		defaults.put("reviewers", listed(reviewers))
	}
	if reflect.DeepEqual(meant(file.get("defaults")), meant(defaults)) {
		return nil
	}
	root, err := load()
	if err != nil {
		return err
	}
	// what Python's load() does beside validate: [tiers] gone, its pace_margin kept where the
	// file has none, and the provider of a harness that hosts providers named by its label
	if tiers, ok := root.get("tiers").(*table); ok && root.get("pace_margin") == nil && tiers.get("pace_margin") != nil {
		root.put("pace_margin", tiers.get("pace_margin"))
	}
	delete(root.values, "tiers")
	hosts, err := manifests()
	if err != nil {
		return err
	}
	for harness, manifest := range hosts {
		block, _ := manifest.get("providers").(*table)
		label, named := block.get("label").(string)
		if entry, ok := root.get("providers").(*table).get(harness).(*table); ok && named {
			entry.put("name", label)
		}
	}
	for _, key := range present(file) {
		if !slices.Contains([]string{"defaults", "tiers", "models", "providers"}, key) {
			root.put(key, file.values[key])
		}
	}
	root.put("defaults", defaults)
	text, err := dump(root)
	if err != nil {
		return err
	}
	tmp := filepath.Join(Home(), "config.tmp")
	if err := os.WriteFile(tmp, []byte(text), 0o600); err != nil {
		return err
	}
	if err := os.Chmod(tmp, 0o600); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

func listed(names []string) []any {
	list := []any{}
	for _, name := range names {
		list = append(list, name)
	}
	return list
}

// meant is [defaults] as remember_defaults compares two: reviewers it leaves out are its workers.
func meant(value any) map[string]any {
	defaults, ok := value.(*table)
	if !ok {
		return nil
	}
	held := map[string]any{"reviewers": defaults.get("workers")}
	for _, key := range present(defaults) {
		held[key] = defaults.values[key]
	}
	return held
}

// present is a table's keys that still hold a value: validate takes a value out and leaves its key.
func present(t *table) []string {
	return slices.DeleteFunc(slices.Clone(t.keys), func(key string) bool {
		_, held := t.values[key]
		return !held
	})
}

// dump is the config as Python's config.dump writes it: the top level's values, then
// [defaults], each [models.*] and [providers.*], each in save's order, then every other table in
// place, each value as Python spells it.
func dump(root *table) (string, error) {
	chunks := [][]string{saveHeader}
	var scalars []string
	for _, key := range present(root) {
		if _, nested := root.values[key].(*table); !nested {
			scalars = append(scalars, key)
		}
	}
	if len(scalars) > 0 {
		lines, err := pairs(root, ordered(scalars, saveOrder[""]))
		if err != nil {
			return "", err
		}
		chunks = append(chunks, lines)
	}
	defaults := root.values["defaults"].(*table)
	lines, err := pairs(defaults, ordered(present(defaults), saveOrder["defaults"]))
	if err != nil {
		return "", err
	}
	chunks = append(chunks, append([]string{"[defaults]"}, lines...))
	for _, group := range []string{"models", "providers"} {
		entries := root.values[group].(*table)
		for _, name := range present(entries) {
			entry, ok := entries.values[name].(*table)
			if !ok {
				return "", fmt.Errorf("cannot write config.toml: [%s.%s] is not a table", group, name)
			}
			lines, err := pairs(entry, ordered(present(entry), saveOrder[group]))
			if err != nil {
				return "", err
			}
			chunks = append(chunks, append([]string{"[" + group + "." + tomlKey(name) + "]"}, lines...))
		}
	}
	for _, key := range present(root) {
		if nested, ok := root.values[key].(*table); ok && !slices.Contains([]string{"defaults", "models", "providers"}, key) {
			if err := section([]string{key}, nested, &chunks); err != nil {
				return "", err
			}
		}
	}
	joined := make([]string, len(chunks))
	for i, chunk := range chunks {
		joined[i] = strings.Join(chunk, "\n")
	}
	return strings.Join(joined, "\n\n") + "\n", nil
}

// section is one table Python's save knows nothing of, and the tables it holds, each written in
// place as config._dump_table writes them.
func section(path []string, t *table, chunks *[][]string) error {
	var plain []string
	for _, key := range present(t) {
		if _, nested := t.values[key].(*table); !nested && tables(t.values[key]) == nil {
			plain = append(plain, key)
		}
	}
	lines, err := pairs(t, plain)
	if err != nil {
		return err
	}
	*chunks = append(*chunks, append([]string{"[" + dotted(path) + "]"}, lines...))
	for _, key := range present(t) {
		inner := slices.Concat(path, []string{key})
		if nested, ok := t.values[key].(*table); ok {
			if err := section(inner, nested, chunks); err != nil {
				return err
			}
		}
		for _, bit := range tables(t.values[key]) {
			entry, ok := bit.(*table)
			if !ok {
				return fmt.Errorf("cannot write config.toml: [%s] mixes tables and values", key)
			}
			lines, err := pairs(entry, present(entry))
			if err != nil {
				return err
			}
			*chunks = append(*chunks, append([]string{"[[" + dotted(inner) + "]]"}, lines...))
		}
	}
	return nil
}

// tables is a list's items where any is a table, which save writes as an array of tables; nil
// for anything else.
func tables(value any) []any {
	var items []any
	switch value := value.(type) {
	case []any:
		items = value
	case tableArray:
		for _, row := range value {
			items = append(items, row)
		}
	}
	if !slices.ContainsFunc(items, func(item any) bool { _, ok := item.(*table); return ok }) {
		return nil
	}
	return items
}

// ordered is keys with those of first in its order ahead, the rest in place (config._ordered).
func ordered(keys, first []string) []string {
	var led []string
	for _, key := range first {
		if slices.Contains(keys, key) {
			led = append(led, key)
		}
	}
	for _, key := range keys {
		if !slices.Contains(first, key) {
			led = append(led, key)
		}
	}
	return led
}

func pairs(t *table, keys []string) ([]string, error) {
	var lines []string
	for _, key := range keys {
		value, err := tomlValue(t.values[key])
		if err != nil {
			return nil, err
		}
		lines = append(lines, tomlKey(key)+" = "+value)
	}
	return lines, nil
}

func dotted(path []string) string {
	keys := make([]string, len(path))
	for i, part := range path {
		keys[i] = tomlKey(part)
	}
	return strings.Join(keys, ".")
}
