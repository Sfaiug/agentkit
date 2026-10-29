// Package config checks configuration before a shadow command reaches an operation.
package config

import (
	_ "embed"
	"fmt"
	"math"
	"math/big"
	"os"
	"path/filepath"
	"reflect"
	"regexp"
	"sort"
	"strconv"
	"strings"

	"agentkit/internal/commandhelp"
)

// Keep the shipped default inside the single binary. The test pins this copy to
// config.default.toml, which remains the source for both implementations.
//
//go:generate cp ../../../config.default.toml default.toml
//go:embed default.toml
var defaultConfig string

func Home() string {
	home, _ := os.UserHomeDir()
	return filepath.Join(home, ".agentkit")
}

// places are the folders ak keeps under Home, in Python's config.PLACES order.
var places = []string{"runs", "wt", "state", "secrets", "tmp", "env", "work", "jobs"}

// EnsureDirs makes Home and its places as Python's config.ensure_dirs does: each owner-only,
// one someone else made included, and a file where one goes refused, never changed.
func EnsureDirs() error {
	if err := os.MkdirAll(filepath.Dir(Home()), 0o777); err != nil {
		return err
	}
	for _, place := range append([]string{""}, places...) {
		dir := filepath.Join(Home(), place)
		if err := os.Mkdir(dir, 0o700); err != nil {
			if info, statErr := os.Stat(dir); statErr != nil || !info.IsDir() {
				return err
			}
		}
		if err := os.Chmod(dir, 0o700); err != nil {
			return err
		}
	}
	return nil
}

func Expand(path string) string {
	if path == "~" || strings.HasPrefix(path, "~/") || strings.HasPrefix(path, "~"+string(filepath.Separator)) {
		home, _ := os.UserHomeDir()
		path = filepath.Join(home, strings.TrimPrefix(path[1:], "/"))
	}
	return filepath.Clean(path)
}

func Absolute(path string) string {
	return Resolve(Expand(path))
}

// Resolve is path made absolute with its links followed, as far as they exist, and a leading
// `~` kept literal, as Python's Path.resolve() reads it.
func Resolve(path string) string {
	path, _ = filepath.Abs(path)
	if resolved, err := filepath.EvalSymlinks(path); err == nil {
		return resolved
	}
	return path
}

// Glob lists the entries of dir whose names match pattern. Dir is a path, never a pattern, as
// Python's Path(dir).glob reads it: a home under "a[b]" still lists its files.
func Glob(dir, pattern string) []string {
	entries, _ := os.ReadDir(dir)
	var paths []string
	for _, entry := range entries {
		if matched, _ := filepath.Match(pattern, entry.Name()); matched {
			paths = append(paths, filepath.Join(dir, entry.Name()))
		}
	}
	return paths
}

func Check() error {
	_, err := load()
	return err
}

func load() (*table, error) {
	path := filepath.Join(Home(), "config.toml")
	data, err := os.ReadFile(path)
	if err != nil && !os.IsNotExist(err) {
		return nil, fmt.Errorf("cannot read %s: %w", path, err)
	}
	root, err := parseDocument(string(data))
	if err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	if !hasTables(root) {
		root, err = parseDocument(defaultConfig)
		path = "config.default.toml"
		if err != nil {
			return nil, fmt.Errorf("%s: %w", path, err)
		}
	}
	if err := validate(root); err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	return root, nil
}

func hasTables(root *table) bool {
	for _, name := range []string{"defaults", "tiers", "models", "providers"} {
		if _, ok := root.values[name]; ok {
			return true
		}
	}
	return false
}

// the most `within` can be: past ten points under the best, a point says nothing
const points = 10

var accountName = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]*$`)

func stringList(value any, nonempty bool) bool {
	list, ok := value.([]any)
	if !ok || (nonempty && len(list) == 0) {
		return false
	}
	seen := map[string]bool{}
	for _, item := range list {
		name, ok := item.(string)
		if !ok || seen[name] {
			return false
		}
		seen[name] = true
	}
	return true
}

func validate(root *table) error {
	models, ok := root.values["models"].(*table)
	if !ok {
		return fmt.Errorf("missing [models] table")
	}
	providers, ok := root.values["providers"].(*table)
	if !ok {
		return fmt.Errorf("missing [providers] table")
	}
	var names []string
	named := map[string]bool{}
	for _, name := range models.keys {
		entry, ok := models.values[name].(*table)
		if ok {
			provider, ok := entry.values["provider"].(string)
			if _, present := providers.values[provider]; ok && present {
				names = append(names, name)
				named[provider] = true
			}
		}
	}
	if len(names) == 0 {
		return fmt.Errorf("no [models.*] entry names a provider with a [providers.*] table")
	}
	for _, name := range providers.keys {
		if entry, ok := providers.values[name].(*table); ok && entry.values["mode"] == "free" && !named[name] {
			delete(providers.values, name)
		}
	}
	if tiers, ok := root.values["tiers"].(*table); ok {
		first, a := tiers.values["A"].([]any)
		rest, b := tiers.values["B"].([]any)
		if _, exists := root.values["defaults"]; !exists && a && b && len(first) > 0 {
			defaults := newTable()
			defaults.put("orchestrator", first[0])
			workers := []any{}
			for _, name := range rest {
				if !reflect.DeepEqual(name, first[0]) {
					workers = append(workers, name)
				}
			}
			defaults.put("workers", workers)
			root.put("defaults", defaults)
		}
	}
	if _, exists := root.values["defaults"]; !exists {
		root.put("defaults", newTable())
	}
	defaults, ok := root.values["defaults"].(*table)
	if !ok {
		return fmt.Errorf("[defaults] must be a table")
	}
	if value, exists := root.values["within"]; exists {
		valid := false
		switch number := value.(type) {
		case *big.Int:
			valid = number.Sign() >= 0 && number.Cmp(big.NewInt(points)) <= 0
		case float64:
			valid = number >= 0 && number <= points
		}
		if !valid {
			return fmt.Errorf("within must be a number of points from 0 to %d (got %s)", points, valueRepr(value))
		}
	}
	if value, exists := root.values["compare"]; exists {
		marks, ok := value.([]any)
		for _, slug := range marks {
			_, valid := slug.(string)
			ok = ok && valid
		}
		if !ok {
			return fmt.Errorf("compare must list release slugs (compare = [\"acme-pro-5\"]) (got %s)", valueRepr(value))
		}
	}
	if _, exists := defaults.values["orchestrator"]; !exists {
		defaults.put("orchestrator", names[0])
	}
	if value := defaults.values["orchestrator"]; value != nil {
		if _, ok := value.(string); !ok {
			return fmt.Errorf("[defaults].orchestrator must be a model name (got %s)", valueRepr(value))
		}
	}
	if _, exists := defaults.values["workers"]; !exists {
		defaults.put("workers", []any{})
	}
	for _, key := range []string{"workers", "reviewers"} {
		if value, exists := defaults.values[key]; exists && !stringList(value, key == "reviewers") {
			return fmt.Errorf("[defaults].%s must list distinct model names (got %s)", key, valueRepr(value))
		}
	}
	for _, name := range providers.keys {
		entry, ok := providers.values[name].(*table)
		if !ok {
			continue
		}
		value, exists := entry.values["accounts"]
		if !exists {
			continue
		}
		valid := stringList(value, false)
		if valid {
			for _, name := range value.([]any) {
				valid = valid && accountName.MatchString(name.(string))
			}
		}
		if !valid {
			return fmt.Errorf("[providers.%s].accounts must list distinct names of letters, digits, '.', '_' and '-' (got %s)", name, valueRepr(value))
		}
	}
	return nil
}

func CheckModel(name string) error {
	root, err := load()
	if err != nil {
		return err
	}
	_, err = resolve(root, name)
	return err
}

// A Model is what a [models.*] entry runs on: its provider and the provider's model id.
type Model struct{ Provider, ID string }

// Models is every entry `resolve` runs.
func Models() (map[string]Model, error) {
	root, err := load()
	if err != nil {
		return nil, err
	}
	models := map[string]Model{}
	for _, name := range root.values["models"].(*table).keys {
		if model, err := resolve(root, name); err == nil {
			models[name] = model
		}
	}
	return models, nil
}

// resolve is the [models.*] entry `config.model` runs, or why it runs none.
func resolve(root *table, name string) (Model, error) {
	models := root.values["models"].(*table)
	value, exists := models.values[name]
	if !exists {
		names := append([]string(nil), models.keys...)
		sort.Strings(names)
		return Model{}, fmt.Errorf("unknown model %s; ~/.agentkit/config.toml defines: %s", commandhelp.Quote(name), strings.Join(names, ", "))
	}
	entry, _ := value.(*table)
	for _, field := range []string{"harness", "model", "effort", "provider"} {
		if entry == nil || entry.values[field] == nil {
			return Model{}, fmt.Errorf("~/.agentkit/config.toml: [models.%s] is missing %s", name, commandhelp.Quote(field))
		}
	}
	provider, valid := entry.values["provider"].(string)
	if _, exists := root.values["providers"].(*table).values[provider]; !valid || !exists {
		return Model{}, fmt.Errorf("~/.agentkit/config.toml: [models.%s].provider=%s has no [providers.*] entry", name, valueRepr(entry.values["provider"]))
	}
	return Model{provider, fmt.Sprint(entry.values["model"])}, nil
}

func valueRepr(value any) string {
	switch value := value.(type) {
	case string:
		return commandhelp.Quote(value)
	case bool:
		if value {
			return "True"
		}
		return "False"
	case []any:
		parts := make([]string, len(value))
		for i, item := range value {
			parts[i] = valueRepr(item)
		}
		return "[" + strings.Join(parts, ", ") + "]"
	case *table:
		var parts []string
		for _, key := range value.keys {
			parts = append(parts, commandhelp.Quote(key)+": "+valueRepr(value.values[key]))
		}
		return "{" + strings.Join(parts, ", ") + "}"
	case float64:
		format := byte('g')
		if math.Abs(value) >= 1e-4 && math.Abs(value) < 1e16 {
			format = 'f'
		}
		text := strings.TrimPrefix(strings.ToLower(strconv.FormatFloat(value, format, -1, 64)), "+")
		if !strings.ContainsAny(text, ".enai") {
			text += ".0"
		}
		return text
	default:
		return fmt.Sprint(value)
	}
}
