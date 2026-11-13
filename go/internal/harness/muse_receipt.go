package harness

import (
	"cmp"
	"crypto/rand"
	"encoding/hex"
	"os"
	"path/filepath"

	"agentkit/internal/agent"
	"agentkit/internal/config"
	"agentkit/internal/run"
)

// museReceiptEnv names a launch's receipt to the hooks on its line (muse.py RECEIPT_ENV).
const museReceiptEnv = "AGENTKIT_MUSE_RECEIPT"

// Muse's TUI takes no session id, so each launch learns its own: a receipt, a folder in state/
// named in its record and its environment, into which its SessionStart links the session Muse
// reported (muse.py).  A resumed session is in it from the start, and the record is left as it is;
// a new session drops the one the record followed to (museFollows).
func museLaunched(_, _, conversation string, _ *run.Object) (*run.Object, []string, error) {
	random := make([]byte, 16)
	rand.Read(random)
	token := hex.EncodeToString(random)
	path := museReceipt(token)
	if err := os.Mkdir(path, 0o700); err != nil {
		return nil, nil, err
	}
	if conversation != "" {
		if err := os.WriteFile(filepath.Join(path, "session"), []byte(conversation), 0o666); err != nil {
			return nil, nil, err
		}
	}
	fields := run.Fields("muse_launch", token)
	if conversation == "" {
		fields.Set("conversation", nil)
	}
	return fields, []string{museReceiptEnv + "=" + path}, nil
}

// museReceipt is the receipt a record's token names, "" for none.
func museReceipt(token string) string {
	if !launchToken.MatchString(token) {
		return ""
	}
	return filepath.Join(config.Home(), "state", "muse-launch-"+token)
}

// museStarted writes a SessionStart into that launch's receipt: the session Muse reported, linked,
// so the first stands; a receipt gone takes nothing.
func museStarted(receipt string, event *run.Object) {
	session := event.Str("session_id")
	if receipt == "" || !museSession.MatchString(session) {
		return
	}
	museWrite(receipt, "session", session)
}

// museHook is the id_source of a session the seat's own Muse completed a turn in (muse.py SOURCE).
const museHook = "muse-hook"

// museConversation is the session the seat's own Muse last completed a turn in (museFollows), else
// the one its launch reported (museReceived), "" where neither names one yet: never one the record
// kept from another harness the seat moved here from (muse.py `conversation`).
func museConversation(record map[string]any) string {
	if conversation, _ := record["conversation"].(string); conversation != "" && record["id_source"] == museHook {
		return conversation
	}
	return museReceived(record)
}

// museReceived is the session that record's launch reported into its receipt, "" for no receipt or
// none reported yet (muse.py `owned`).
func museReceived(record map[string]any) string {
	token, _ := record["muse_launch"].(string)
	return museRead(museReceipt(token), "session")
}

// museFollows is the session a turn's end names (muse.py `follow`): `/new` fires no hook, but a Stop
// the seat's own Muse fires moves the seat to the session its turn ran in, Muse waiting on each, so
// they come in turn order.  An Interrupt keeps the session it names beside the seat's, and moves
// nothing: Muse runs it only alongside the turn (museInteractive), so it may land after a later
// turn's Stop.  Only a session with a log in Muse's own store, which its words are read from.
func museFollows(event *run.Object) *Followed {
	name := event.Str("hook_event_name")
	if name != "Stop" && name != "Interrupt" {
		return nil
	}
	var log any // none, as Python's claim takes a log it found and nothing else
	if found := museLog(event.Str("session_id")); found != "" {
		log = found
	}
	return &Followed{Harness: "muse", Source: museHook, Conversation: event.Get("session_id"), Transcript: log,
		Client: museClient, Filed: museLog, Keep: name == "Interrupt"}
}

// museClient is whether a process runs the seat's Muse (muse.py `is_process`): its launcher, or the
// build that launcher execs, by the names its adapter gives them (orch.agent_programs).
func museClient(words []string) bool {
	names, err := config.ProgramsOf("muse")
	return err == nil && agent.Named(words, names)
}

// museReported is the session that launch reported, which the line it opened on went into; "" where
// it reported none yet.  A receipt Muse's registry moved on, before a seat followed its Stops
// instead, keeps that one as `reported` and the one it moved to as its session (muse.py `reported`).
func museReported(record map[string]any) string {
	token, _ := record["muse_launch"].(string)
	path := museReceipt(token)
	return cmp.Or(museRead(path, "reported"), museRead(path, "session"))
}

// museRead is the session that receipt's file names, "" for none or no receipt.
func museRead(receipt, name string) string {
	session, _ := museNames(receipt, name)
	return session
}

// museWrite puts text whole in the receipt's file `name`, linked, so the first stands.
func museWrite(receipt, name, text string) {
	file, err := os.CreateTemp(receipt, "."+name+".")
	if err != nil {
		return
	}
	defer os.Remove(file.Name())
	_, err = file.WriteString(text)
	if file.Close() == nil && err == nil {
		os.Link(file.Name(), filepath.Join(receipt, name))
	}
}
