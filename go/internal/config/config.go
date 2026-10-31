// Package config checks configuration before a shadow command reaches an operation.
package config

import (
	"cmp"
	"context"
	_ "embed"
	"errors"
	"fmt"
	"math"
	"math/big"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"regexp"
	"runtime"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"

	"agentkit/internal/commandhelp"
)

// Keep the shipped default inside the single binary. The test pins this copy to
// config.default.toml, which remains the source for both implementations.
//
//go:generate cp ../../../config.default.toml default.toml
//go:embed default.toml
var defaultConfig string

func Home() string {
	return filepath.Join(UserHome(), ".agentkit")
}

// Repo is the checkout ak runs from, Python's config.REPO: the top of the git checkout its
// resolved executable sits in, else the folder above the executable's bin/, as in a copied tree.
func Repo() string {
	executable, err := os.Executable()
	if err != nil {
		return ""
	}
	if resolved, err := filepath.EvalSymlinks(executable); err == nil {
		executable = resolved
	}
	bin := filepath.Dir(executable)
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if top, err := exec.CommandContext(ctx, "git", "-C", bin, "rev-parse", "--show-toplevel").Output(); err == nil {
		return filepath.Clean(strings.TrimSuffix(string(top), "\n"))
	}
	return filepath.Dir(bin)
}

// places are the folders ak keeps under Home, in Python's config.PLACES order.
var places = []string{"runs", "wt", "state", "secrets", "tmp", "env", "work", "jobs"}

// EnsureDirs makes Home and its places as Python's config.ensure_dirs does: each owner-only,
// one someone else made included, and a file where one goes refused, never changed.  Failing,
// it takes back what it made and changed, so its caller can leave all of the work to Python.
func EnsureDirs() (err error) {
	var undo []func()
	defer func() {
		for i := len(undo) - 1; err != nil && i >= 0; i-- {
			undo[i]()
		}
	}()
	// the folders missing above Home, outermost first, as Python's parents=True makes them
	var above []string
	for dir := filepath.Dir(Home()); dir != filepath.Dir(dir); dir = filepath.Dir(dir) {
		if _, err := os.Stat(dir); err == nil {
			break
		}
		above = append([]string{dir}, above...)
	}
	for _, dir := range above {
		if err := os.Mkdir(dir, 0o777); err != nil {
			return err
		}
		undo = append(undo, func() { os.Remove(dir) })
	}
	for _, place := range append([]string{""}, places...) {
		dir := filepath.Join(Home(), place)
		before, statErr := os.Stat(dir)
		if err := os.Mkdir(dir, 0o700); err == nil {
			undo = append(undo, func() { os.Remove(dir) })
		} else if statErr != nil || !before.IsDir() {
			return err
		}
		if err := os.Chmod(dir, 0o700); err != nil {
			return err
		}
		if statErr == nil {
			// its whole mode: Chmod sets the setuid, setgid and sticky bits too
			undo = append(undo, func() { os.Chmod(dir, before.Mode()) })
		}
	}
	return nil
}

func Expand(path string) string {
	return filepath.Clean(tilde(path))
}

// Absolute is path as Python's Path(path).expanduser().resolve() reads it: the rest as spelled,
// so a `..` after a link leaves the link's target.
func Absolute(path string) string {
	return Resolve(tilde(path))
}

// tilde is path with a leading `~` put in the home's place as Python's expanduser puts it, the
// rest as spelled.
func tilde(path string) string {
	if path != "~" && !strings.HasPrefix(path, "~/") && !strings.HasPrefix(path, "~"+string(filepath.Separator)) {
		return path
	}
	return cmp.Or(strings.TrimRight(UserHome(), "/"+string(filepath.Separator))+path[1:], "/")
}

// Resolve is path made absolute with its links followed, as far as they exist, and a leading
// `~` kept literal, as Python's Path.resolve() reads it: name by name, so a `..` after a link
// leaves the link's target, and a link that loops is kept as it is.  On Windows, Python takes
// each `..` away first.  A relative path stays as given while the current directory cannot be
// read, where Python's getcwd fails.
func Resolve(path string) string {
	if runtime.GOOS == "windows" {
		absolute, err := filepath.Abs(path)
		if err != nil {
			return path
		}
		if resolved, err := filepath.EvalSymlinks(absolute); err == nil {
			return resolved
		}
		return absolute
	}
	if !filepath.IsAbs(path) {
		cwd, err := os.Getwd()
		if err != nil {
			return path
		}
		path = cwd + "/" + path
	}
	// rest is the names still to follow, the next last; a step with a link marks where that
	// link's target is resolved.
	type step struct{ name, link string }
	var rest []step
	push := func(path string) {
		names := strings.Split(path, "/")
		for i := len(names) - 1; i >= 0; i-- {
			rest = append(rest, step{name: names[i]})
		}
	}
	push(path)
	resolved, seen := "/", map[string]string{} // a link's resolved target, "" while it resolves
	for len(rest) > 0 {
		next := rest[len(rest)-1]
		rest = rest[:len(rest)-1]
		switch {
		case next.link != "":
			seen[next.link] = resolved
			continue
		case next.name == "" || next.name == ".":
			continue
		case next.name == "..":
			resolved = cmp.Or(resolved[:strings.LastIndexByte(resolved, '/')], "/")
			continue
		}
		joined := strings.TrimSuffix(resolved, "/") + "/" + next.name
		info, err := os.Lstat(joined)
		if err != nil || info.Mode()&os.ModeSymlink == 0 {
			resolved = joined
			continue
		}
		if target, ok := seen[joined]; ok {
			resolved = cmp.Or(target, joined)
			continue
		}
		target, err := os.Readlink(joined)
		if err != nil {
			resolved = joined
			continue
		}
		if strings.HasPrefix(target, "/") {
			resolved = "/"
		}
		seen[joined] = ""
		rest = append(rest, step{link: joined})
		push(target)
	}
	return resolved
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
	if err := Manifests(); err != nil {
		return nil, err
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

// ModelNamed is the [models.*] entry name, or why there is none, Python's config.model.
func ModelNamed(name string) (Model, error) {
	root, err := load()
	if err != nil {
		return Model{}, err
	}
	return resolve(root, name)
}

// Harnesses is each harness the config's models run on, once, in the order the file names them.
func Harnesses() ([]string, error) {
	root, err := load()
	if err != nil {
		return nil, err
	}
	var names []string
	models := root.values["models"].(*table)
	for _, name := range models.keys {
		if entry, ok := models.values[name].(*table); ok {
			if harness, ok := entry.values["harness"].(string); ok && !slices.Contains(names, harness) {
				names = append(names, harness)
			}
		}
	}
	return names, nil
}

// A Model is what a [models.*] entry runs on: its provider, the provider's model id, the
// harness that runs it, and the efforts it sets, by their RoleEfforts keys.
type Model struct {
	Provider, ID, Harness string
	Efforts               map[string]string
}

// RoleEfforts are the keys an entry's efforts go under, a seat's first (config.ROLE_EFFORTS).
var RoleEfforts = []string{"effort", "exec_effort", "review_effort"}

// TurnEffort is the effort a worker turn runs at, a review's review_effort and any other's
// exec_effort, else effort, as Python's config.role_effort reads them.
func (m Model) TurnEffort(review bool) string {
	key := "exec_effort"
	if review {
		key = "review_effort"
	}
	if effort, set := m.Efforts[key]; set {
		return effort
	}
	return m.Efforts["effort"]
}

// Offered is every model the config offers, in config.offered's order: a harness where its
// first model is in the file, its models in file order under it.
func Offered() ([]string, error) {
	root, err := load()
	if err != nil {
		return nil, err
	}
	var harnesses []string
	under := map[string][]string{}
	models := root.values["models"].(*table)
	for _, name := range models.keys {
		entry, _ := models.values[name].(*table)
		if entry == nil {
			continue
		}
		harness, named := entry.values["harness"].(string)
		provider, valid := entry.values["provider"].(string)
		if _, exists := root.values["providers"].(*table).values[provider]; named && valid && exists {
			if under[harness] == nil {
				harnesses = append(harnesses, harness)
			}
			under[harness] = append(under[harness], name)
		}
	}
	var names []string
	for _, harness := range harnesses {
		names = append(names, under[harness]...)
	}
	return names, nil
}

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

// A Binding is what a launch outside any seat binds from the config, as Python's
// capture_launch binds it: [defaults]' workers and reviewers as load() keeps them to the models
// offered, Reviewers nil where it names none, and the effort keys of each [models.*] table.
type Binding struct {
	Workers, Reviewers []any
	Models             []string
	Efforts            map[string][][2]string
}

// errUnbound is a config Go binds otherwise than Python: [defaults] efforts, which stand in for
// the models' own, or an effort that is no string.
var errUnbound = errors.New("a config Go binds otherwise than Python")

// Bind is the home config's Binding.
func Bind() (Binding, error) {
	root, err := load()
	if err != nil {
		return Binding{}, err
	}
	defaults, models := root.values["defaults"].(*table), root.values["models"].(*table)
	if _, held := defaults.values["efforts"]; held {
		return Binding{}, errUnbound
	}
	bound := Binding{Efforts: map[string][][2]string{}}
	var offered []any // a model naming a harness, and a provider with a table
	for _, name := range models.keys {
		entry, ok := models.values[name].(*table)
		if !ok {
			continue
		}
		bound.Models = append(bound.Models, name)
		for _, key := range RoleEfforts {
			if value, set := entry.values[key]; set {
				effort, ok := value.(string)
				if !ok {
					return Binding{}, errUnbound
				}
				bound.Efforts[name] = append(bound.Efforts[name], [2]string{key, effort})
			}
		}
		_, harness := entry.values["harness"].(string)
		provider, named := entry.values["provider"].(string)
		if _, listed := root.values["providers"].(*table).values[provider]; harness && named && listed {
			offered = append(offered, name)
		}
	}
	if len(offered) == 0 {
		return Binding{}, errUnbound
	}
	// load() passes over a model no longer offered, the first offered taking a list it empties;
	// executors written empty beside reviewers stay empty
	kept := func(key string) (kept []any) {
		listed, _ := defaults.values[key].([]any)
		for _, name := range listed {
			if slices.Contains(offered, name) {
				kept = append(kept, name)
			}
		}
		return kept
	}
	workers, _ := defaults.values["workers"].([]any)
	_, written := defaults.values["workers"]
	_, reviews := defaults.values["reviewers"]
	if bound.Workers = kept("workers"); bound.Workers == nil && (len(workers) > 0 || !written || !reviews) {
		bound.Workers = offered[:1]
	}
	if bound.Reviewers = kept("reviewers"); reviews && bound.Reviewers == nil {
		bound.Reviewers = offered[:1]
	}
	return bound, nil
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
	harness, _ := entry.values["harness"].(string)
	efforts := map[string]string{}
	for _, key := range RoleEfforts {
		if word, ok := entry.values[key].(string); ok {
			efforts[key] = word
		}
	}
	return Model{provider, fmt.Sprint(entry.values["model"]), harness, efforts}, nil
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
