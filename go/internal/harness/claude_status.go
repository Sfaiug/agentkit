package harness

// claudeStatus is where Claude Code reads the owner's status command, the seat's folder first,
// the login's own last (adapters/claude.sh `interactive`).
var claudeStatus = []string{".claude/settings.local.json", ".claude/settings.json",
	"${CLAUDE_CONFIG_DIR:-~/.claude}/settings.json"}
