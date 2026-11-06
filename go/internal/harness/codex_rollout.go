package harness

import (
	"bufio"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	"agentkit/internal/config"
	"agentkit/internal/lock"
	"agentkit/internal/run"
)

// codexLaunch is the record's key naming its launch's receipt, and codexSource the `id_source` of
// a thread that receipt proves (codex.py SOURCE).
const codexLaunch, codexSource = "codex_launch", "codex-session-start"

// launchToken is a launch receipt's own name for itself (codex.py `path_for`).
var launchToken = regexp.MustCompile(`^[0-9a-f]{32}$`)

// codexKept are the files state/ holds for a Codex seat beside its record (codex.py `path_for`,
// `remote_home` and its `.forgotten` mark), each named by a uuid4's hex.
var codexKept = regexp.MustCompile(`^codex-(?:launch-[0-9a-f]{32}\.json|remote-[0-9a-f]{32}(?:\.forgotten)?)$`)

// codexReceipt is the receipt of the launch the record names (codex.py `read`), read under the
// lock its SessionStart hook writes it in place under, which never makes the file; nil where it
// names none, another launch's, or none that reads.
func codexReceipt(record *run.Object) *run.Object {
	token := record.Str(codexLaunch)
	if !launchToken.MatchString(token) {
		return nil
	}
	file, err := lock.Edit(filepath.Join(config.Home(), "state", "codex-launch-"+token+".json"))
	if err != nil {
		return nil
	}
	defer file.Close()
	data, err := io.ReadAll(file)
	if err != nil {
		return nil
	}
	value, _ := run.Decode(data)
	receipt, _ := value.(*run.Object)
	if receipt == nil || receipt.Get("launch") != token {
		return nil
	}
	return receipt
}

// codexThread is the thread the seat owns and the rollout Codex keeps it in (codex.py
// `conversation` and `transcript`): the one its launch's SessionStart reported, unambiguous, opened
// in the receipt's own directory, and so recorded in that rollout's first line.  "" for none.
func codexThread(record *run.Object) (thread, rollout string) {
	receipt := codexReceipt(record)
	if receipt == nil || receipt.Truthy("ambiguous") || receipt.Dict("event") == nil {
		return "", ""
	}
	event := receipt.Dict("event")
	sid, _ := event.Get("session_id").(string)
	rollout, _ = event.Get("transcript_path").(string)
	cwd, _ := receipt.Get("cwd").(string)
	source := event.Get("source")
	if sid == "" || strings.HasPrefix(sid, "-") || !filepath.IsAbs(rollout) || !filepath.IsAbs(cwd) ||
		event.Get("hook_event_name") != "SessionStart" || source != "startup" && source != "resume" ||
		event.Get("cwd") != cwd || receipt.Get("expected") != nil && receipt.Get("expected") != sid ||
		record.Str("id_source") == codexSource && record.Get("conversation") != sid {
		return "", ""
	}
	file, err := os.Open(rollout)
	if err != nil {
		return "", ""
	}
	defer file.Close()
	first, _ := bufio.NewReader(file).ReadBytes('\n')
	value, _ := run.Decode(first)
	meta, _ := value.(*run.Object)
	if meta == nil || meta.Get("type") != "session_meta" || meta.Dict("payload") == nil ||
		meta.Dict("payload").Get("id") != sid || meta.Dict("payload").Get("cwd") != cwd {
		return "", ""
	}
	return sid, rollout
}

// codexOwns is whether the receipt proves that thread the seat's (orch.owns).
func codexOwns(record *run.Object, conversation string) bool {
	thread, _ := codexThread(record)
	return thread == conversation
}

// codexRecord hands Python a record whose proven thread no reconcile has bound yet (codexReconcile
// is the tick's). Without one, including at prepare's startup chooser, the screen still says the
// seat's word; legacy ids stay untouched.
func codexRecord(_ string, record *run.Object) (plugin, bool) {
	thread, rollout := codexThread(record)
	ready := thread == "" || record.Get("conversation") == thread &&
		record.Get("id_source") == codexSource && record.Get("resumable") == true
	launch := record.Str(codexLaunch)
	path := func(current *run.Object) string {
		if current.Str(codexLaunch) != launch || current.Str("id_source") == codexSource && current.Get("conversation") != thread {
			return ""
		}
		return rollout
	}
	own := plugins["codex"]
	own.owns = func(current *run.Object, conversation string) bool {
		return path(current) != "" && conversation == thread
	}
	own.recorded = func(current *run.Object) (string, bool) { return codexErrorAt(path(current)) }
	own.answer = func(current *run.Object) (any, any, any, bool) { return codexAnswerAt(path(current)) }
	return own, ready
}

// codexError is the error Codex recorded as the end of the seat's thread's last turn (codex.py
// `error`): a failed turn ends in a `task_complete` whose `error` holds the message the seat
// showed, a `task_started` after it is a newer prompt, and the last item of a turn in flight says
// the same.  False where the seat owns no thread or its rollout cannot be read.
func codexError(record *run.Object) (string, bool) {
	_, rollout := codexThread(record)
	return codexErrorAt(rollout)
}

func codexErrorAt(rollout string) (string, bool) {
	if rollout == "" {
		return "", false
	}
	kind := func(entry *run.Object) string {
		if payload := entry.Dict("payload"); payload != nil && entry.Str("type") == "event_msg" {
			return payload.Str("type")
		}
		return ""
	}
	entry, err := lastEntry(rollout, func(entry *run.Object) bool {
		return entry.Str("type") == "response_item" || kind(entry) == "task_started" || kind(entry) == "task_complete"
	})
	if err != nil {
		return "", false
	}
	if entry == nil || kind(entry) != "task_complete" || entry.Dict("payload").Dict("error") == nil {
		return "", true
	}
	message, _ := entry.Dict("payload").Dict("error").Get("message").(string)
	return strings.TrimFunc(message, config.Space), true
}

// codexAnswer is the model and effort of the turn that holds the seat's thread's latest answer,
// and that answer's time (codex.py `running`): Codex records them as a turn starts
// (`turn_context`), so `/model` typed in the seat shows at its next answer, and a turn that never
// answered shows nothing.
func codexAnswer(record *run.Object) (model, effort, at any, found bool) {
	_, rollout := codexThread(record)
	return codexAnswerAt(rollout)
}

func codexAnswerAt(rollout string) (model, effort, at any, found bool) {
	if rollout == "" {
		return nil, nil, nil, false
	}
	var answered *run.Object
	entry, _ := lastEntry(rollout, func(entry *run.Object) bool {
		if answered == nil && codexAnswered(entry) {
			answered = entry
		}
		payload := entry.Dict("payload")
		if answered == nil || entry.Str("type") != "turn_context" || payload == nil {
			return false
		}
		_, named := payload.Get("model").(string)
		return named
	})
	if entry == nil {
		return nil, nil, nil, false
	}
	return entry.Dict("payload").Get("model"), entry.Dict("payload").Get("effort"), answered.Get("timestamp"), true
}

// codexAnswered is whether that rollout line is a completed answer with words in it, commentary
// or final (codex.py `answer`): an AgentMessage's parts are `Text`, a UserMessage's `text`.
func codexAnswered(entry *run.Object) bool {
	payload := entry.Dict("payload")
	if entry.Str("type") != "event_msg" || payload == nil || payload.Str("type") != "item_completed" ||
		payload.Dict("item") == nil || payload.Dict("item").Str("type") != "AgentMessage" {
		return false
	}
	var said []string
	for _, part := range payload.Dict("item").List("content") {
		if part, _ := part.(*run.Object); part != nil && (part.Str("type") == "text" || part.Str("type") == "Text") {
			if text, ok := part.Get("text").(string); ok {
				said = append(said, text)
			}
		}
	}
	return strings.Join(said, "\n") != ""
}
