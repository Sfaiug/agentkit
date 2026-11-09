package harness

import (
	"os"
	"path/filepath"
	"regexp"
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

// A Store is where a harness that never ends a conversation itself keeps them: the harness, a
// folder, the pattern under it of one conversation's file, or its folder where the pattern ends
// in `/`, and what that name matches whole, its first group the conversation's id.
type Store struct {
	Harness, Root, Pattern string
	ID                     *regexp.Regexp
}

var (
	anyName     = regexp.MustCompile(`^(.+)$`)
	agyFile     = regexp.MustCompile(`^(.+)\.db$`)
	rolloutFile = regexp.MustCompile(`^rollout-.+-([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})\.jsonl$`)
)

// ConversationStores is every such harness's stores, in the plugins' order: agy 1.4.4's default
// home; ~/.codex/sessions and each Codex seat's sessions and archived sessions, kept apart; each
// Grok login home's sessions not linked to another's; Muse's session folders.  `list` is a
// folder's names in order, read as the caller's plan reads: HOME's own access time stays.
func ConversationStores(list func(folder string) []string) []Store {
	home := config.UserHome()
	stores := []Store{{"antigravity", filepath.Join(home, ".gemini", "antigravity-cli", "conversations"), "*.db", agyFile}}
	rollouts := "*/*/*/rollout-*.jsonl"
	stores = append(stores, Store{"codex", filepath.Join(home, ".codex", "sessions"), rollouts, rolloutFile})
	for _, seat := range listed(list, filepath.Join(home, ".codex", "agentkit-seats"), func(path string) bool {
		info, err := os.Stat(path)
		return err == nil && info.IsDir()
	}) {
		stores = append(stores, Store{"codex", filepath.Join(seat, "sessions"), rollouts, rolloutFile},
			Store{"codex", filepath.Join(seat, "archived_sessions"), rollouts, rolloutFile})
	}
	grok := append([]string{filepath.Join(home, ".grok")}, listed(list, home, func(path string) bool {
		return strings.HasPrefix(filepath.Base(path), ".grok-")
	})...)
	for _, each := range grok {
		if info, err := os.Lstat(filepath.Join(each, "sessions")); err != nil || info.Mode()&os.ModeSymlink == 0 {
			stores = append(stores, Store{"grokbuild", filepath.Join(each, "sessions"), "*/*/", anyName})
		}
	}
	return append(stores, Store{"muse", filepath.Join(share(), "muse", "sessions"), "[0-9]*/[0-9]*/[0-9]*/*/", anyName})
}

// An Idle is a conversation a harness keeps as rows of its own database and never ends itself:
// the harness, and the conversation's id.
type Idle struct{ Harness, ID string }

// IdleConversations is each such conversation that is top-level and nobody updated since
// `before`, in Unix seconds, which takes its children along when it ends: OpenCode's, the one
// harness keeping any.  False where Go reads one otherwise than Python does.
func IdleConversations(before float64) ([]Idle, bool) {
	sessions, known := opencodeIdle(before)
	idle := make([]Idle, len(sessions))
	for i, session := range sessions {
		idle[i] = Idle{"opencode", session}
	}
	return idle, known
}

// EndIdle ends that conversation, children and all, its harness's own way, only where
// ends(its database) holds right before it starts: whether it went.
func EndIdle(idle Idle, ends func(database string) bool) (bool, error) {
	return opencodeEnd(idle.ID, ends)
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
func listed(list func(string) []string, folder string, passes func(string) bool) []string {
	var found []string
	for _, name := range list(folder) {
		if path := filepath.Join(folder, name); passes(path) {
			found = append(found, path)
		}
	}
	return found
}
