package harness

import (
	"fmt"
	"maps"
	"os"
	"path/filepath"
	"reflect"
	"slices"
	"strings"
	"unicode/utf8"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/run"
)

const (
	codexBegin = "# --- agentkit browser bridge: managed by `ak browser mcp-register` ---"
	codexEnd   = "# --- end agentkit browser bridge ---"
)

// codexRegisterMCP keeps the servers in one marked block of ~/.codex/config.toml, and nothing
// else, as codex.py's `register_mcp`.  A block, not a rewrite: install.sh and Codex both own keys
// in this file, and a round trip through a TOML writer would lose their comments and their order.
// A marker counts only as a line of its own, so a comment quoting one is no block; and the new
// file must parse to the old one with only these servers and the old block's changed, or nothing
// is written.
func codexRegisterMCP(servers []Server) (string, error) {
	path := filepath.Join(config.UserHome(), ".codex", "config.toml")
	raw, _, err := readConfig(path)
	if err != nil {
		return "", err
	}
	before, err := config.ReadTOML(raw)
	if err != nil {
		return "", fmt.Errorf("%s is not valid TOML, so nothing was changed: %v", path, err)
	}
	ours := map[string]bool{}
	for _, server := range servers {
		ours[server.Name] = true
	}
	block := codexBlock(servers)
	lines := keptLines(raw)
	var begins, ends []int
	for i, line := range lines {
		switch strings.TrimFunc(line, config.Space) {
		case codexBegin:
			begins = append(begins, i)
		case codexEnd:
			ends = append(ends, i)
		}
	}
	var text string
	if begins != nil || ends != nil {
		if len(begins) != 1 || len(ends) != 1 || ends[0] < begins[0] {
			return "", fmt.Errorf("%s has half of the agentkit block or more than one; repair or delete the lines from %s to %s and run this again",
				path, commandhelp.Quote(codexBegin), commandhelp.Quote(codexEnd))
		}
		start, stop := begins[0], ends[0]+1
		// the servers the old block held are ours to replace, renamed ones too
		if old, err := config.ReadTOML(strings.Join(lines[start:stop], "")); err == nil {
			if held, ok := old["mcp_servers"].(map[string]any); ok {
				for name := range held {
					ours[name] = true
				}
			}
		}
		text = strings.Join(lines[:start], "") + block
		if tail := strings.TrimLeft(strings.Join(lines[stop:], ""), "\n"); tail != "" {
			text += "\n" + tail
		}
	} else {
		held, _ := before["mcp_servers"].(map[string]any)
		var clash []string
		for _, name := range slices.Sorted(maps.Keys(ours)) {
			if _, ok := held[name]; ok {
				clash = append(clash, name)
			}
		}
		if clash != nil {
			return "", fmt.Errorf("%s already defines mcp_servers.%s outside the agentkit block; remove those tables and run this again",
				path, strings.Join(clash, ", mcp_servers."))
		}
		if strings.TrimFunc(raw, config.Space) != "" {
			text = strings.TrimRight(raw, "\n") + "\n\n"
		}
		text += block
	}
	result, err := config.ReadTOML(text)
	if err != nil {
		return "", fmt.Errorf("the block this would write does not parse: %v", err)
	}
	if tookNoEffect(result, servers) {
		return "", fmt.Errorf("%s: the block did not take effect", path)
	}
	if !reflect.DeepEqual(outsideServers(result, ours), outsideServers(before, ours)) {
		return "", fmt.Errorf("%s: registering would change settings outside the agentkit block, so nothing was changed; move them out from between %s and %s and run this again",
			path, commandhelp.Quote(codexBegin), commandhelp.Quote(codexEnd))
	}
	if text == raw {
		return "already registered in " + path, nil
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return "", fmt.Errorf("cannot write %s: %s", path, config.PyError(err))
	}
	if err := writeConfig(path, text); err != nil {
		return "", err
	}
	return "registered in " + path, nil
}

// codexBlock is the servers as the one marked block; a TOML basic string escapes as JSON's does.
func codexBlock(servers []Server) string {
	lines := []string{codexBegin}
	for _, server := range servers {
		lines = append(lines, "[mcp_servers."+server.Name+"]")
		if server.URL != "" {
			lines = append(lines, "url = "+run.Line(server.URL))
		} else {
			args := make([]string, len(server.Args))
			for i, arg := range server.Args {
				args[i] = run.Line(arg)
			}
			var env []string
			for _, key := range slices.Sorted(maps.Keys(server.Env)) {
				env = append(env, key+" = "+run.Line(server.Env[key]))
			}
			lines = append(lines, "command = "+run.Line(server.Command),
				"args = ["+strings.Join(args, ", ")+"]",
				"env = { "+strings.Join(env, ", ")+" }")
		}
		lines = append(lines, "")
	}
	return strings.Join(append(lines, codexEnd), "\n") + "\n"
}

// tookNoEffect is whether the file parses to fewer servers than these and no others: markers
// quoted inside a multi-line string put the block in that string.
func tookNoEffect(result map[string]any, servers []Server) bool {
	held, _ := result["mcp_servers"].(map[string]any)
	found := 0
	for _, server := range servers {
		if _, ok := held[server.Name]; ok {
			found++
		}
	}
	return found == len(held) && found < len(servers)
}

// outsideServers is a parsed config less the MCP servers named: what registering them leaves alone.
func outsideServers(data map[string]any, names map[string]bool) map[string]any {
	servers, ok := data["mcp_servers"].(map[string]any)
	if !ok {
		return data
	}
	kept := maps.Clone(servers)
	maps.DeleteFunc(kept, func(name string, _ any) bool { return names[name] })
	rest := maps.Clone(data)
	delete(rest, "mcp_servers")
	if len(kept) > 0 {
		rest["mcp_servers"] = kept
	}
	return rest
}

// keptLines is text as Python's str.splitlines(keepends=True) cuts it, a text file's every `\r`
// already read as a newline.
func keptLines(text string) []string {
	var lines []string
	start := 0
	for i, r := range text {
		if strings.ContainsRune("\n\v\f\x1c\x1d\x1e\u0085  ", r) {
			lines = append(lines, text[start:i+utf8.RuneLen(r)])
			start = i + utf8.RuneLen(r)
		}
	}
	if start < len(text) {
		lines = append(lines, text[start:])
	}
	return lines
}
