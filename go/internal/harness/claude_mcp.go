package harness

import (
	"errors"
	"fmt"
	"maps"
	"path/filepath"
	"slices"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

// claudeRegisterMCP puts the servers into ~/.claude.json's top-level mcpServers, user scope, as
// claude.py's `register_mcp`.  An entry of the same name from before is replaced whole, leaving no
// stale command behind, and every other key stays where it was.
func claudeRegisterMCP(servers []Server) (string, error) {
	path := filepath.Join(config.UserHome(), ".claude.json")
	data := run.NewObject()
	text, found, err := readConfig(path)
	if err != nil {
		return "", err
	}
	if found {
		value, err := run.DecodeLimited([]byte(text))
		if errors.Is(err, run.ErrLimit) || errors.Is(err, run.ErrLoneSurrogate) {
			return "", ErrPython
		}
		if err != nil {
			return "", fmt.Errorf("%s: %v", path, err)
		}
		object, ok := value.(*run.Object)
		if !ok {
			return "", fmt.Errorf("%s: expected a JSON object", path)
		}
		data = object
	}
	merged, ok := data.Get("mcpServers").(*run.Object)
	if !ok {
		if data.Get("mcpServers") != nil {
			return "", fmt.Errorf("%s: mcpServers is not an object", path)
		}
		merged = run.NewObject()
	}
	registered := true
	for _, server := range servers {
		entry := claudeEntry(server)
		registered = registered && sameJSON(merged.Get(server.Name), entry)
		merged.Set(server.Name, entry)
	}
	if registered {
		return "already registered in " + path + " (user scope)", nil
	}
	data.Set("mcpServers", merged)
	if err := writeConfig(path, run.Line(data)+"\n"); err != nil {
		return "", err
	}
	return "registered in " + path + " (user scope)", nil
}

// claudeEntry is a server as Claude reads one: a URL is its `http` server, a command its `stdio`.
func claudeEntry(server Server) *run.Object {
	entry := run.NewObject()
	if server.URL != "" {
		entry.Set("type", "http")
		entry.Set("url", server.URL)
		return entry
	}
	args := make([]any, len(server.Args))
	for i, arg := range server.Args {
		args[i] = arg
	}
	env := run.NewObject()
	for _, key := range slices.Sorted(maps.Keys(server.Env)) {
		env.Set(key, server.Env[key])
	}
	entry.Set("type", "stdio")
	entry.Set("command", server.Command)
	entry.Set("args", args)
	entry.Set("env", env)
	return entry
}

// sameJSON is whether a value read equals an entry of strings, as Python's == reads two dicts:
// whatever order their keys came in.
func sameJSON(read, wanted any) bool {
	switch wanted := wanted.(type) {
	case string:
		return read == wanted
	case []any:
		list, ok := read.([]any)
		return ok && slices.EqualFunc(list, wanted, sameJSON)
	case *run.Object:
		object, ok := read.(*run.Object)
		if !ok || len(object.Keys()) != len(wanted.Keys()) {
			return false
		}
		for _, key := range wanted.Keys() {
			if !object.Has(key) || !sameJSON(object.Get(key), wanted.Get(key)) {
				return false
			}
		}
		return true
	}
	return false
}
