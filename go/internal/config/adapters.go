package config

import (
	"context"
	"embed"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"slices"
	"strings"
	"time"

	"agentkit/internal/commandhelp"
)

// The adapter manifests ship inside the single binary; the test pins these copies to
// adapters/, which remains the source for both implementations.
//
//go:generate sh -c "rm -f adapters/*.toml && cp ../../../adapters/*.toml adapters/"
//go:embed adapters/*.toml
var adapters embed.FS

// SeatEnv is the variables a launch sets for its seat alone, as the manifests' `[launch]
// seat_env` declare them: nothing the seat starts may be told them, or a check would run
// to the orchestrator's rules.
func SeatEnv() ([]string, error) {
	var names []string
	for _, harness := range harnesses() {
		root, err := manifest(harness)
		if err != nil {
			return nil, err
		}
		launch, _ := root.values["launch"].(*table)
		if launch == nil {
			continue
		}
		listed, _ := launch.values["seat_env"].([]any)
		for _, each := range listed {
			if each, ok := each.(string); ok {
				names = append(names, each)
			}
		}
	}
	return names, nil
}

// AgentPrograms are the names, as patterns, a process in a pane goes by when it is an agent:
// each harness's own, the program its `[update] version` command runs, and the `[launch]
// programs` that one goes on to run.
func AgentPrograms() []string {
	var found []string
	for _, harness := range harnesses() {
		found = append(found, harness)
		root, err := manifest(harness)
		if err != nil {
			continue
		}
		if update, ok := root.values["update"].(*table); ok {
			if version, _ := update.values["version"].([]any); len(version) > 0 {
				if program, ok := version[0].(string); ok {
					found = append(found, filepath.Base(program))
				}
			}
		}
		if launch, ok := root.values["launch"].(*table); ok {
			programs, _ := launch.values["programs"].([]any)
			for _, each := range programs {
				if pattern, ok := each.(string); ok {
					found = append(found, pattern)
				}
			}
		}
	}
	return found
}

// harnesses are those with a manifest: the shipped ones and $AGENTKIT_ADAPTER_DIR's.
func harnesses() []string {
	shipped, _ := fs.Glob(adapters, "adapters/*.toml")
	if dir := os.Getenv("AGENTKIT_ADAPTER_DIR"); dir != "" {
		shipped = append(shipped, Glob(Expand(dir), "*.toml")...)
	}
	var names []string
	for _, each := range shipped {
		if name := strings.TrimSuffix(filepath.Base(each), ".toml"); !slices.Contains(names, name) {
			names = append(names, name)
		}
	}
	return names
}

// Repo is the top of the checkout this ak was built in, where adapters/ and tools/ are.
func Repo() string {
	executable, err := os.Executable()
	if err != nil {
		return ""
	}
	if resolved, err := filepath.EvalSymlinks(executable); err == nil {
		executable = resolved
	}
	dir := filepath.Dir(executable)
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if top, err := exec.CommandContext(ctx, "git", "-C", dir, "rev-parse", "--show-toplevel").Output(); err == nil {
		return strings.TrimSpace(string(top))
	}
	return dir
}

// Adapter is the script that runs a harness, adapters/<harness>.sh, under
// $AGENTKIT_ADAPTER_DIR where it names another directory.
func Adapter(harness string) (string, error) {
	dir := filepath.Join(Repo(), "adapters")
	if override := os.Getenv("AGENTKIT_ADAPTER_DIR"); override != "" {
		dir = Expand(override)
	}
	path := filepath.Join(dir, harness+".sh")
	info, err := os.Stat(path)
	if err != nil {
		return "", fmt.Errorf("no adapter for harness %s: %s does not exist", commandhelp.Quote(harness), path)
	}
	if info.Mode()&0111 == 0 {
		return "", fmt.Errorf("adapter %s is not executable; chmod +x it", path)
	}
	return path, nil
}

var defaulted = regexp.MustCompile(`\$\{(\w+):-([^}]*)\}`)
var placeholder = regexp.MustCompile(`\$(?:\$|([A-Za-z_]\w*)|\{([A-Za-z_]\w*)\})`)

// Unswitched are the files under the home a harness reads on its own and its adapter cannot
// switch off (`[instructions] unswitched`), for env, the environment it runs in: `~/` is its
// home, `$NAME` and `${NAME:-default}` its variables, and a path naming one unset or empty is
// none.  An env naming no account looks in the usual home too, where an adapter drops an
// account's home a seat handed down.
func Unswitched(harness string, env map[string]string) ([]string, error) {
	root, err := manifest(harness)
	if err != nil {
		return nil, err
	}
	var names []string
	block, _ := root.values["instructions"].(*table)
	if block != nil {
		listed, _ := block.values["unswitched"].([]any)
		for _, each := range listed {
			if name, _ := each.(string); strings.HasPrefix(name, "~") || strings.HasPrefix(name, "$") {
				names = append(names, name)
			}
		}
	}
	found := resolveAll(names, env)
	if env["AGENTKIT_ACCOUNT"] == "" {
		for _, path := range resolveAll(names, map[string]string{"HOME": env["HOME"]}) {
			if !slices.Contains(found, path) {
				found = append(found, path)
			}
		}
	}
	return found, nil
}

func resolveAll(names []string, env map[string]string) []string {
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
		missing := false
		name = placeholder.ReplaceAllStringFunc(name, func(match string) string {
			parts := placeholder.FindStringSubmatch(match)
			value, ok := values[parts[1]+parts[2]]
			if match == "$$" {
				value, ok = "$", true
			}
			missing = missing || !ok
			return value
		})
		if !missing {
			name, _ = filepath.Abs(name)
			paths = append(paths, name)
		}
	}
	return paths
}

// manifest is adapters/<harness>.toml, $AGENTKIT_ADAPTER_DIR's where it has one; a harness
// with none reads as an empty one.
func manifest(harness string) (*table, error) {
	name := harness + ".toml"
	data, err := adapters.ReadFile("adapters/" + name)
	if dir := os.Getenv("AGENTKIT_ADAPTER_DIR"); dir != "" {
		own := filepath.Join(Expand(dir), name)
		if _, missing := os.Stat(own); missing == nil {
			if data, err = os.ReadFile(own); err != nil {
				return nil, fmt.Errorf("%s: %w", own, errors.Unwrap(err))
			}
		}
	}
	if err != nil {
		return newTable(), nil
	}
	root, err := parseDocument(string(data))
	if err != nil {
		return nil, fmt.Errorf("adapter manifest %s: %w", name, err)
	}
	return root, nil
}
