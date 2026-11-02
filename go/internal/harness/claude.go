package harness

import (
	"bytes"
	"io"
	"os"
	"strconv"
	"strings"
	"unicode/utf16"

	"agentkit/internal/run"
)

// A Claude seat resumes the conversation its record names (claude.py `resumable`).  Its turn's
// shell takes the done-when ceiling as its default and its most, so its own default need not
// send a command to the background; the heartbeats Claude streams while a tool blocks are still
// no activity to the silence watchdog.
func init() {
	ceiling := strconv.Itoa(run.CeilingHours * 3600 * 1000)
	plugins["claude"] = plugin{seats: true, answer: claudeAnswer, conversation: claudeConversation, notices: claudeNotices, auth: claudeAuth, lend: claudeLend, turnEnv: map[string]string{
		"BASH_DEFAULT_TIMEOUT_MS": ceiling, "BASH_MAX_TIMEOUT_MS": ceiling}, opens: true, titled: true}
}

// claudeNotices are the interruptions Claude Code writes as a user line (claude.py INTERRUPTS).
var claudeNotices = map[string][]string{"[Request interrupted by user": {"]", " for tool use]"}}

// projectCut is where Claude Code ends a project folder's name with a hash of the path.
const projectCut = 200

// claudeAnswer is the last answer a conversation records (claude.py `running`), read back from
// its end: its own, never a subagent's or one Claude Code made up itself. Read anywhere else
// Claude Code would keep it, or not read, there is none.
func claudeAnswer(conversation, cwd string) (model, effort any, found bool) {
	file, err := os.Open(claudeConversation(map[string]any{"conversation": conversation, "cwd": cwd}))
	if err != nil {
		return nil, nil, false
	}
	defer file.Close()
	end, err := file.Seek(0, io.SeekEnd)
	var rest []byte
	for err == nil && end > 0 {
		start := max(0, end-65536)
		chunk := make([]byte, end-start, end-start+int64(len(rest)))
		if _, err = file.ReadAt(chunk, start); err != nil {
			break
		}
		lines := bytes.Split(append(chunk, rest...), []byte("\n"))
		rest = nil
		if start > 0 { // the head of a line the next read ends
			rest, lines = lines[0], lines[1:]
		}
		for at := len(lines) - 1; at >= 0; at-- {
			value, _ := run.Decode(lines[at])
			entry, _ := value.(*run.Object)
			if entry == nil || entry.Str("type") != "assistant" || entry.Truthy("isSidechain") || entry.Dict("message") == nil {
				continue
			}
			if model = entry.Dict("message").Get("model"); model != nil && model != "<synthetic>" {
				return model, entry.Get("effort"), true
			}
		}
		end = start
	}
	return nil, nil, false
}

// projectFolder is the folder Claude Code files a working directory's conversations under
// (claude.py `project`): each UTF-16 unit not an ASCII letter or digit a hyphen, and a long
// name its start and the magnitude of the path's 31-times hash as a signed 32-bit number.
func projectFolder(cwd string) string {
	var name strings.Builder
	for _, char := range cwd {
		switch {
		case char < 0x80 && (char >= '0' && char <= '9' || char >= 'a' && char <= 'z' || char >= 'A' && char <= 'Z'):
			name.WriteRune(char)
		case char > 0xFFFF:
			name.WriteString("--")
		default:
			name.WriteByte('-')
		}
	}
	if name.Len() <= projectCut {
		return name.String()
	}
	var hash uint32
	for _, unit := range utf16.Encode([]rune(cwd)) {
		hash = hash*31 + uint32(unit)
	}
	magnitude := int64(int32(hash))
	if magnitude < 0 {
		magnitude = -magnitude
	}
	return name.String()[:projectCut] + "-" + strconv.FormatInt(magnitude, 36)
}
