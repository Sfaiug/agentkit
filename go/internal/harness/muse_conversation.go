package harness

import (
	"bufio"
	"errors"
	"io/fs"
	"iter"
	"os"
	"path/filepath"
	"slices"
	"syscall"

	"agentkit/internal/hookfact"
	"agentkit/internal/run"
)

// Muse logs a session as the run events of its session.jsonl (1.4.12): each run opens on the
// prompt it was given and commits every answer it showed as an event of its own; its reasoning,
// tool batches and reminders are other events, and a child session is a log of its own.  Each
// question card going up and its settling, answered or Esc's `interrupted`, is logged too, named
// by its prompt and tool call, hooks or none: `/new` leaves a launch's hooks behind (muse.py).

// museLog is the log Muse keeps that session in, its first under YYYY/MM/DD/<session>/, "" for none
// (muse.py `session_log`).
func museLog(session string) string {
	log, _ := museLogFound(session)
	return log
}

// museLogFound is museLog, and where it finds none, the error of a folder or log it could not look
// at, which may hold it: one that says nothing is there, or no folder, hides none.
func museLogFound(session string) (string, error) {
	if !museSession.MatchString(session) {
		return "", nil
	}
	var unread error
	hidden := func(err error) {
		if unread == nil && err != nil && !errors.Is(err, fs.ErrNotExist) && !errors.Is(err, syscall.ENOTDIR) {
			unread = err
		}
	}
	// read, not globbed: the data home is a path, whatever pattern characters it holds
	folders := []string{filepath.Join(share(), "muse", "sessions")}
	for range 3 {
		var deeper []string
		for _, folder := range folders {
			entries, err := os.ReadDir(folder)
			hidden(err)
			for _, entry := range entries {
				deeper = append(deeper, filepath.Join(folder, entry.Name()))
			}
		}
		folders = deeper
	}
	for _, folder := range folders {
		log := filepath.Join(folder, session, "session.jsonl")
		_, err := os.Stat(log)
		if err == nil {
			return log, nil
		}
		hidden(err)
	}
	return "", unread
}

// exists is whether a file is at that path, through links, as a glob finds one.
func exists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}

// museEntries is each JSON object of a session's log, first line first; an unfinished last line
// can wait.
func museEntries(path string) iter.Seq[*run.Object] {
	return func(yield func(*run.Object) bool) {
		file, err := os.Open(path)
		if err != nil {
			return
		}
		defer file.Close()
		for reader := bufio.NewReader(file); ; {
			line, err := reader.ReadBytes('\n')
			value, _ := run.DecodeShown(line)
			if entry, ok := value.(*run.Object); ok && !yield(entry) || err != nil {
				return
			}
		}
	}
}

// field is the value under those keys, each in the object the last one held; nil where one is
// missing or holds no object.
func field(value any, keys ...string) any {
	for _, key := range keys {
		object, _ := value.(*run.Object)
		if object == nil {
			return nil
		}
		value = object.Get(key)
	}
	return value
}

// museRunEvent is one log line's run event of that kind, nil for none.
func museRunEvent(entry *run.Object, kind string) *run.Object {
	if field(entry, "payload", "kind") != "run" {
		return nil
	}
	event, _ := field(entry, "payload", "event").(*run.Object)
	if field(event, "kind") != kind {
		return nil
	}
	return event
}

// museTyped is what the user side typed that one log line holds: a run's prompt, or a line steered
// into a running turn as the run drains it.  A steer that opens a run of its own is that run's
// prompt; background tasks' notices are drained from another source.
func museTyped(entry *run.Object) string {
	if started := museRunEvent(entry, "started"); started != nil && started.Truthy("prompt") {
		return started.Str("prompt")
	}
	steer, _ := field(museRunEvent(entry, "inbox_item_drained"), "delivery_snapshot").(*run.Object)
	source, _ := field(steer, "source").(*run.Object)
	if source == nil || len(source.Keys()) != 1 || source.Get("source") != "user_steer" {
		return ""
	}
	return steer.Str("body")
}

// museTyping is what museTyped reads in that session, dated when Muse recorded it, in seconds; a
// line dated otherwise is nobody's answer (muse.py `user_messages`).
func museTyping(session string) (typed []Prompt) {
	for entry := range museEntries(museLog(session)) {
		micro, whole := entry.Int("recorded_at")
		if text := museTyped(entry); whole && text != "" {
			typed = append(typed, Prompt{float64(micro) / 1e6, text})
		}
	}
	return typed
}

// museSaid is that session's conversation as its chat shows it, oldest first, none where it has no
// log.  The chat shows a run's first final answer, one with no `phase`, to its prompt or a steer,
// and none after it: 1.4.12 logs a later one its own end-of-turn reminder asked for that no screen
// of it ever displays.
func museSaid(session string) (said []Turn) {
	answered := map[string]bool{}
	for entry := range museEntries(museLog(session)) {
		if turn, shown := museTurn(entry, answered); shown {
			said = append(said, turn)
		}
	}
	return said
}

// museTurn is the turn that log line adds to museSaid's conversation, false for none, answered
// holding the runs whose prompt or latest steer a shown final answered so far.
func museTurn(entry *run.Object, answered map[string]bool) (Turn, bool) {
	run, _ := field(entry, "payload", "run_id").(string)
	if text := museTyped(entry); text != "" {
		delete(answered, run)
		return Turn{"user", text}, true
	}
	event := museRunEvent(entry, "assistant_message_committed")
	if event == nil {
		return Turn{}, false
	}
	if !event.Truthy("phase") {
		if answered[run] {
			return Turn{}, false
		}
		answered[run] = run != ""
	}
	text := event.Str("text")
	return Turn{"model", text}, text != ""
}

// museCard is Muse's own question card in that session, as the fact its hooks write for it
// (adapters/muse.toml), dated when Muse recorded it; false where it asked none.  The newest card is
// up until a settling of that same card follows it, and down from that moment: its answer runs the
// turn on, and an Esc rests the seat until its next prompt, which Muse reports by no hook, so from
// that prompt on the turn the Esc ended is just over.
func museCard(session string) (hookfact.Fact, bool) {
	type settling struct {
		entry, event *run.Object
		prompted     bool // a prompt came after it
	}
	same := func(a, b *run.Object) bool {
		return run.Equal(a.Get("prompt_id"), b.Get("prompt_id")) && run.Equal(a.Get("tool_call_id"), b.Get("tool_call_id"))
	}
	log := museLog(session)
	if log == "" {
		return hookfact.Fact{}, false
	}
	var settled []settling // read newest first: the first of a card's is its last
	prompted := false
	entry, err := lastEntry(log, func(entry *run.Object) bool {
		if museRunEvent(entry, "started") != nil {
			prompted = true
		}
		if done := museRunEvent(entry, "user_input_prompt_settled"); done != nil &&
			!slices.ContainsFunc(settled, func(each settling) bool { return same(each.event, done) }) {
			settled = append(settled, settling{entry, done, prompted})
		}
		return museRunEvent(entry, "user_input_prompt_requested") != nil
	})
	if err != nil || entry == nil {
		return hookfact.Fact{}, false
	}
	asked := museRunEvent(entry, "user_input_prompt_requested")
	if _, named := asked.Get("prompt_id").(string); !named {
		return hookfact.Fact{}, false
	}
	down := settling{entry, run.NewObject(), false}
	if at := slices.IndexFunc(settled, func(each settling) bool { return same(each.event, asked) }); at >= 0 {
		down = settled[at]
	}
	micro, whole := down.entry.Int("recorded_at")
	at := float64(micro) / 1e6
	switch {
	case !whole:
		return hookfact.Fact{}, false
	case down.event.Get("outcome") == "answered":
		return hookfact.Fact{Event: "PostToolBatch", Kind: "request_user_input", At: at}, true
	case down.event.Truthy("outcome") && down.prompted:
		return hookfact.Fact{Event: "Stop", At: at}, true
	case down.event.Truthy("outcome"):
		return hookfact.Fact{Event: "Interrupt", At: at}, true
	}
	questions := asked.List("questions")
	text := ""
	if len(questions) > 0 {
		text, _ = field(questions[0], "question").(string)
	}
	return hookfact.Fact{Event: "Notification", Kind: "question_prompt", Text: text, At: at}, true
}

// museAnswer is the model of the latest answer or completed /model change in the seat's session
// (Muse 1.4.14), at its own time (muse.py `running`).  Neither records effort: `reminder_roster`'s
// are its reminder subagents', and settings.json holds whatever any session picked last, so the
// seat keeps the effort its record holds.
func museAnswer(record *run.Object) (model, effort, at any, found bool) {
	modelOf := func(entry *run.Object) any {
		if entry.Get("payload_type") != "runtime.model_reconfigure.completed" {
			return field(museRunEvent(entry, "model_completed"), "model")
		}
		return field(entry, "payload", "record", "effective", "model_id")
	}
	log := museLog(museOwned(record))
	if log == "" {
		return nil, nil, nil, false
	}
	entry, err := lastEntry(log, func(entry *run.Object) bool {
		_, named := modelOf(entry).(string)
		_, whole := entry.Int("recorded_at")
		return named && whole
	})
	if err != nil || entry == nil {
		return nil, nil, nil, false
	}
	micro, _ := entry.Int("recorded_at")
	return modelOf(entry), field(record, "efforts", record.Str("orchestrator"), "effort"), run.Float(float64(micro) / 1e6), true
}

// museOwned is the session the seat's receipt names (museConversation), "" for none.
func museOwned(record *run.Object) string {
	return museConversation(map[string]any{"muse_launch": record.Get("muse_launch")})
}

// museResumable is whether the seat owns a session to resume: the receipt is the whole answer, as
// the launcher never issues a Muse id (muse.py `resumable`).
func museResumable(record *run.Object) bool { return museOwned(record) != "" }
