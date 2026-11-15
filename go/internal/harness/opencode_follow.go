package harness

import (
	"errors"
	"io"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"slices"

	"agentkit/internal/agent"
	"agentkit/internal/config"
	"agentkit/internal/run"
)

func init() { verbs["opencode receipt"] = opencodeReceiptVerb }

// opencodeFollows is a prompt the seat's own OpenCode took into a top-level session, whoever typed
// it, its first one too (opencode.py `follow`): opencode.db, which keeps every session and so is
// each one's file, says which as the prompt is reported, a subagent's session naming the one that
// started it there, and never followed.  The session the seat is in then goes into its launch's
// receipt (opencodeReceived).
func opencodeFollows(event *run.Object) *Followed {
	session := event.Str("session_id")
	if event.Get("hook_event_name") != "UserPromptSubmit" || !opencodeSession.MatchString(session) || !opencodeTop(session) {
		return nil
	}
	return &Followed{Harness: "opencode", Conversation: session, Transcript: opencodeDatabase(), Client: opencodeClient,
		Filed: func(map[string]any, string) string { return opencodeDatabase() }, From: opencodeCounted, Then: opencodeReceived}
}

// opencodeTop is whether opencode.db holds that session as a top-level one: not where it cannot be
// read, as Python's reads no row there.
func opencodeTop(session string) bool {
	conn, _ := opencodeOpen()
	if conn == nil {
		return false
	}
	defer conn.Close()
	row, err := opencodeRow(conn, "SELECT 1 FROM session_v2 WHERE id = ? AND parent_id IS NULL", session)
	return err == nil && row != nil
}

// opencodeClient is whether a process runs OpenCode (orch.program names it `opencode`).
func opencodeClient(words []string) bool { return agent.Program(words, false) == "opencode" }

// opencodeCounted is the process a hook whose parent is pid counts the seat's OpenCode from.
// 2.2.7's TUI runs its server, the plugin reporting the prompt in it, as a child of its own,
// `opencode serve --stdio`: a process whose command starts so, and which an OpenCode started
// straight, counts from that OpenCode up, so a server started under the seat's own is a second.
// Any other OpenCode counts itself: a server whose parent is a tool's shell, and a TUI whose
// `--prompt` names that command.
func opencodeCounted(pid int) int {
	words, parent := agent.Process(pid)
	above, _ := agent.Process(parent)
	command := slices.Index(words, agent.Program(words, true)) + 1
	if opencodeClient(words) && opencodeClient(above) && slices.Equal(words[command:min(command+2, len(words))], []string{"serve", "--stdio"}) {
		return parent
	}
	return pid
}

// opencodeReceived has `ak adapter - opencode receipt` write the launch's receipt, a process of its
// own the hook waits on, as Python's hook waits on its interpreter: OpenCode's plugin ends a hook
// still running after 5 seconds, which leaves that process to land a write that stalled.
func opencodeReceived(launched string) {
	if self, err := os.Executable(); err == nil {
		exec.Command(self, "adapter", "-", "opencode", "receipt", launched).Run()
	}
}

// opencodeReceiptVerb is opencodeReceive of the seat launched as its one argument.
func opencodeReceiptVerb(args []string, _, _ io.Writer) int {
	if len(args) == 1 {
		opencodeReceive(args[0])
	}
	return 0
}

// opencodeReceive puts the session the seat is in into its launch's receipt, whole and renamed
// over the last one, and only into the launch's own folder, which a seat stopped since has had
// removed: what its record names as it stands, never a session the claim refused, and again until
// the receipt names that.  No lock waits on a hook that stalls: one stalled in its write lands an
// older prompt's session late, by its rename or into the receipt itself, where a later hook
// renamed the same `session.next` already, and so looks again.
func opencodeReceive(launched string) {
	for {
		_, record, err := config.ResolveSession(launched)
		token, _ := record["opencode_launch"].(string)
		current, _ := record["conversation"].(string)
		if err != nil || !launchToken.MatchString(token) || !opencodeSession.MatchString(current) {
			return
		}
		receipt, next := filepath.Join(opencodeReceipt(token), "session"), filepath.Join(opencodeReceipt(token), "session.next")
		if info, err := os.Stat(receipt); err == nil && info.Mode().IsRegular() {
			if said, err := os.ReadFile(receipt); err != nil || string(said) == current {
				return
			}
		}
		if os.WriteFile(next, []byte(current), 0o666) != nil {
			return // the receipt says what it said before
		}
		// gone where another hook renamed it, perhaps after this one's write landed: it looks again
		if err := os.Rename(next, receipt); err != nil && !errors.Is(err, fs.ErrNotExist) {
			return
		}
	}
}
