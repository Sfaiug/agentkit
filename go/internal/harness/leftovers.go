package harness

import (
	"os"
	"path/filepath"
	"slices"
	"strings"
	"unicode"

	"agentkit/internal/config"
)

// What each harness leaves on the host for ak's collector to judge, as Python's plugins say it
// with config_entries, conversation_stores, idle_conversations and tmp_rule.

// A ConfigEntry is a harness file holding the trust and MCP entries ak writes there, read as JSON
// or TOML by its suffix, and the tables they are kept in.
type ConfigEntry struct{ File, Trust, MCP string }

// ConfigEntries is every harness's, in the plugins' order: the user-scope ~/.claude.json, and
// ~/.codex/config.toml.
func ConfigEntries() []ConfigEntry {
	home := config.UserHome()
	return []ConfigEntry{
		{filepath.Join(home, ".claude.json"), "projects", "mcpServers"},
		{filepath.Join(home, ".codex", "config.toml"), "projects", "mcp_servers"},
	}
}

// A Store is where a harness that never ends a conversation itself keeps them: a folder, and the
// pattern under it of one conversation's file, or its folder where the pattern ends in `/`.
type Store struct{ Root, Pattern string }

// ConversationStores is every such harness's stores, in the plugins' order: agy 1.4.4's default
// home; ~/.codex/sessions and each Codex seat's sessions and archived sessions, kept apart; each
// Grok login home's sessions not linked to another's; Muse's session folders.
func ConversationStores() []Store {
	home := config.UserHome()
	stores := []Store{{filepath.Join(home, ".gemini", "antigravity-cli", "conversations"), "*.db"}}
	rollouts := "*/*/*/rollout-*.jsonl"
	stores = append(stores, Store{filepath.Join(home, ".codex", "sessions"), rollouts})
	for _, seat := range listed(filepath.Join(home, ".codex", "agentkit-seats"), func(path string) bool {
		info, err := os.Stat(path)
		return err == nil && info.IsDir()
	}) {
		stores = append(stores, Store{filepath.Join(seat, "sessions"), rollouts}, Store{filepath.Join(seat, "archived_sessions"), rollouts})
	}
	grok := append([]string{filepath.Join(home, ".grok")}, listed(home, func(path string) bool {
		return strings.HasPrefix(filepath.Base(path), ".grok-")
	})...)
	for _, each := range grok {
		if info, err := os.Lstat(filepath.Join(each, "sessions")); err != nil || info.Mode()&os.ModeSymlink == 0 {
			stores = append(stores, Store{filepath.Join(each, "sessions"), "*/*/"})
		}
	}
	return append(stores, Store{filepath.Join(share(), "muse", "sessions"), "[0-9]*/[0-9]*/[0-9]*/*/"})
}

// ConversationDatabases is each SQLite file a harness keeps its conversations in as rows, which
// Python reads for its idle ones: OpenCode's opencode.db, as OpenCode resolves it.
func ConversationDatabases() []string {
	name, set := os.LookupEnv("OPENCODE_DB")
	if !set {
		name = "opencode.db"
	}
	if filepath.IsAbs(name) {
		return []string{name}
	}
	return []string{filepath.Join(share(), "opencode", name)}
}

// OwnsTmp is whether a harness's plugin judges that top-level temporary entry its own way:
// Claude's scratch, `claude-<uid>`, wherever its adapter is installed.
func OwnsTmp(name string) bool {
	uid, ok := strings.CutPrefix(name, "claude-")
	if !ok || uid == "" || strings.IndexFunc(uid, func(r rune) bool { return !unicode.IsDigit(r) }) >= 0 {
		return false
	}
	roots := []string{filepath.Join(config.Repo(), "adapters")}
	if override := os.Getenv("AGENTKIT_ADAPTER_DIR"); override != "" {
		roots = append(roots, config.Expand(override))
	}
	return slices.ContainsFunc(roots, func(root string) bool {
		_, err := os.Lstat(filepath.Join(root, "claude.sh"))
		return err == nil
	})
}

// share is the user's data folder, $XDG_DATA_HOME or ~/.local/share.
func share() string {
	if folder := os.Getenv("XDG_DATA_HOME"); folder != "" {
		return folder
	}
	return filepath.Join(config.UserHome(), ".local", "share")
}

// listed is the entries of a folder that pass, in name order.
func listed(folder string, passes func(string) bool) []string {
	var found []string
	entries, _ := os.ReadDir(folder)
	for _, entry := range entries {
		if path := filepath.Join(folder, entry.Name()); passes(path) {
			found = append(found, path)
		}
	}
	return found
}
