package config

import (
	"embed"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"path"
	"path/filepath"
	"regexp"
	"slices"
	"strings"

	"agentkit/internal/commandhelp"
)

// The adapter manifests ship inside the single binary; the test pins these copies to
// adapters/, which remains the source for both implementations.
//
//go:generate sh -c "rm -f adapters/*.toml && cp ../../../adapters/*.toml adapters/"
//go:embed adapters/*.toml
var adapters embed.FS

// adapterDir names another directory of adapters, how the offline suites run with no model.
const adapterDir = "AGENTKIT_ADAPTER_DIR"

// ErrNoAdapterDir is a home naming no $AGENTKIT_ADAPTER_DIR, as every real home: where Python
// ak's adapter scripts live is not yet Go's to know.
var ErrNoAdapterDir = errors.New("no adapter directory named")

// Adapter is the script that runs a harness, <harness>.sh in $AGENTKIT_ADAPTER_DIR, as Python's
// config.adapter finds it there, or why it cannot be run.
func Adapter(harness string) (string, error) {
	dir := os.Getenv(adapterDir)
	if dir == "" {
		return "", ErrNoAdapterDir
	}
	script := filepath.Join(Expand(dir), harness+".sh")
	if _, err := os.Stat(script); err != nil {
		return "", fmt.Errorf("no adapter for harness %s: %s does not exist", commandhelp.Quote(harness), script)
	}
	if _, err := exec.LookPath(script); err != nil {
		return "", fmt.Errorf("adapter %s is not executable; chmod +x it", script)
	}
	return script, nil
}

// manifests is every adapter's manifest by its name, $AGENTKIT_ADAPTER_DIR's of a harness first,
// else the first in file order that is not TOML, named by its file as Python's config.manifest
// names it.
func manifests() (map[string]*table, error) {
	found := map[string]*table{}
	read := func(file string, data []byte) error {
		root, err := parseDocument(string(data))
		if err != nil {
			return fmt.Errorf("%s: %w", file, err)
		}
		found[strings.TrimSuffix(filepath.Base(file), ".toml")] = root
		return nil
	}
	shipped, _ := fs.Glob(adapters, "adapters/*.toml")
	for _, each := range shipped {
		data, _ := adapters.ReadFile(each)
		if err := read(each, data); err != nil {
			return nil, err
		}
	}
	if dir := os.Getenv(adapterDir); dir != "" {
		for _, each := range Glob(Expand(dir), "*.toml") {
			data, err := os.ReadFile(each)
			if err != nil {
				return nil, fmt.Errorf("cannot read %s: %w", each, err)
			}
			if err := read(each, data); err != nil {
				return nil, err
			}
		}
	}
	return found, nil
}

// Section is one table of a harness's manifest, nil where it has none.
func Section(harness, name string) (map[string]any, error) {
	manifests, err := manifests()
	if err != nil {
		return nil, err
	}
	if root, ok := manifests[harness]; ok {
		if block, ok := root.values[name].(*table); ok {
			return block.values, nil
		}
	}
	return nil, nil
}

// Words is the strings a harness's manifest lists under one key of one section.
func Words(harness, section, key string) ([]string, error) {
	manifests, err := manifests()
	return words(manifests[harness], section, key), err
}

var (
	defaulted   = regexp.MustCompile(`\$\{(\w+):-([^}]*)\}`)
	placeholder = regexp.MustCompile(`(?i)\$(?:(\$)|([_a-z][_a-z0-9]*)|\{([_a-z][_a-z0-9]*)\}|)`)
)

// ManifestPaths is each of a manifest's paths resolved for env, the environment the harness
// runs in, as Python's config.manifest_paths: `~/` is its home, `$VARIABLE` and
// `${VARIABLE:-default}` its variables, and a relative path is under cwd.  A path naming a
// variable that is unset or empty, with no default, is left out.
func ManifestPaths(names []string, env map[string]string, cwd string) []string {
	values := map[string]string{}
	for key, value := range env {
		if value != "" {
			values[key] = value
		}
	}
	if values["HOME"] == "" {
		values["HOME"], _ = os.UserHomeDir()
	}
	var paths []string
	for _, name := range names {
		name = defaulted.ReplaceAllStringFunc(name, func(match string) string {
			parts := defaulted.FindStringSubmatch(match)
			if value := values[parts[1]]; value != "" {
				return value
			}
			return parts[2]
		})
		if rest, ok := strings.CutPrefix(name, "~/"); ok {
			name = "$HOME/" + rest
		}
		named := true
		name = placeholder.ReplaceAllStringFunc(name, func(match string) string {
			parts := placeholder.FindStringSubmatch(match)
			value, ok := values[parts[2]+parts[3]]
			if parts[1] != "" {
				value, ok = "$", true
			}
			named = named && ok
			return value
		})
		if !named {
			continue
		}
		if !filepath.IsAbs(name) {
			name = cwd + string(filepath.Separator) + name // its `..` left for Resolve to take after links
		}
		paths = append(paths, name)
	}
	return paths
}

// SeatEnv is the variables a launch sets for its seat alone, as the manifests' `[launch]
// seat_env` declare them: nothing the seat starts may be told them, or a check would run
// to the orchestrator's rules.
func SeatEnv() ([]string, error) {
	manifests, err := manifests()
	var names []string
	for _, root := range manifests {
		names = append(names, words(root, "launch", "seat_env")...)
	}
	return names, err
}

// Programs is the names a harness's process goes by, as patterns: each adapter's own name,
// the first word of its `[update] version` command (`grok` for Grok's), and its `[launch]
// programs`, what that command goes on to run (Muse's launcher execs `muse-bin-<build>`).
func Programs() ([]string, error) {
	manifests, err := manifests()
	var names []string
	for name, root := range manifests {
		names = append(names, name)
		if version := words(root, "update", "version"); len(version) > 0 {
			names = append(names, path.Base(version[0]))
		}
		names = append(names, words(root, "launch", "programs")...)
	}
	return names, err
}

// A HookTable is a manifest's `[hooks.install]`: the settings file its harness reads hooks
// from, under the login's home where it names `{home}`, and what of ak's hooks/ runs there,
// event by event in the table's order.
type HookTable struct {
	Settings string
	// File is whether that file is ak's own (`form = "file"`), written whole, not merged into.
	File bool
	// Login is whether it is under the login's home (`{home}`): each login has its own.
	Login  bool
	Events []HookEvent
	// Names is each script's own name, then those it went by before: an entry naming one is
	// that script's.
	Names map[string][]string
}

// A HookEvent is one event's scripts, the tools it is matched to ("" for all), and whether it
// is only heard, run in the background.
type HookEvent struct {
	Name, Matcher string
	Scripts       []string
	Heard         bool
}

// Hooks is the harness's `[hooks.install]` table, false where its manifest has none.
func Hooks(harness string) (HookTable, bool, error) {
	manifests, err := manifests()
	hooks, _ := manifests[harness].get("hooks").(*table)
	install, _ := hooks.get("install").(*table)
	settings, _ := install.get("settings").(string)
	events, _ := install.get("events").(*table)
	if err != nil || settings == "" || events == nil {
		return HookTable{}, false, err
	}
	found := HookTable{File: install.get("form") == "file", Login: strings.Contains(settings, "{home}"),
		Names: map[string][]string{}}
	found.Settings = strings.ReplaceAll(Expand(settings), "{home}", loginHome(manifests[harness]))
	matchers, _ := install.get("matchers").(*table)
	heard := words(hooks, "install", "heard")
	for _, name := range events.keys {
		matcher, _ := matchers.get(name).(string)
		scripts := words(install, "events", name)
		found.Events = append(found.Events, HookEvent{name, matcher, scripts, slices.Contains(heard, name)})
		for _, script := range scripts {
			found.Names[script] = append([]string{script}, words(install, "formerly", script)...)
		}
	}
	return found, true, nil
}

// fixedEfforts are the effort words of a harness whose manifest names none (config.EFFORTS).
var fixedEfforts = []string{"low", "medium", "high", "xhigh", "max", "ultra"}

// Efforts are the effort words that harness's model takes, as config.efforts reads them where
// no login has listed the harness's models: its manifest's `[catalog]` row, else its `[effort]
// levels` where each is a word, else the fixed list.
func Efforts(harness, model string) ([]string, error) {
	manifests, err := manifests()
	root := manifests[harness]
	if err != nil || root == nil {
		return fixedEfforts, err
	}
	if catalog, ok := root.values["catalog"].(*table); ok {
		if listed := words(catalog, model, "efforts"); len(listed) > 0 {
			return listed, nil
		}
	}
	levels := words(root, "effort", "levels")
	if block, ok := root.values["effort"].(*table); ok && len(levels) > 0 && len(levels) == len(block.values["levels"].([]any)) && !slices.Contains(levels, "") {
		return levels, nil
	}
	return fixedEfforts, nil
}

// words is the strings a manifest lists under one key of one section.
func words(root *table, section, key string) (found []string) {
	if block, ok := root.get(section).(*table); ok {
		listed, _ := block.values[key].([]any)
		for _, each := range listed {
			if each, ok := each.(string); ok {
				found = append(found, each)
			}
		}
	}
	return found
}
