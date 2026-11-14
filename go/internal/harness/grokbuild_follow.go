package harness

import (
	"path/filepath"

	"agentkit/internal/agent"
	"agentkit/internal/run"
)

// grokHook is the id_source of a session the seat's own Grok ran a prompt in (grokbuild.py
// SOURCE).
const grokHook = "grokbuild-hook"

// grokOwns is whether the record names that session on a launcher-issued id or one its own Grok
// ran a prompt in (grokbuild.py `resumable`).
func grokOwns(record *run.Object, conversation string) bool {
	source := record.Str("id_source")
	return record.Str("conversation") == conversation && (source == "launcher" || source == grokHook)
}

// grokFollows is the session a prompt the seat's own Grok ran names, whoever typed it (grokbuild.py
// `follow`): in 1.0.46 only a prompt names the session /new, Ctrl+N or /dashboard went to, so the
// last the seat ran one in is the one its screen showed last.  A session's first prompt names no
// transcript, its updates.jsonl not yet written: the file of that session in the directory it was
// typed in is the one it is about to write.
func grokFollows(event *run.Object) *Followed {
	if event.Get("hook_event_name") != "UserPromptSubmit" {
		return nil
	}
	session, transcript := event.Get("session_id"), event.Get("transcript_path")
	id, named := session.(string)
	cwd, placed := event.Get("cwd").(string)
	if transcript == nil && named && placed {
		transcript = grokUpdates(cwd, id)
	}
	return &Followed{Harness: "grokbuild", Source: grokHook, Conversation: session, Transcript: transcript,
		Client: grokClient, Filed: func(record map[string]any, conversation string) string {
			cwd, _ := record["cwd"].(string)
			return grokUpdates(cwd, conversation)
		}}
}

// grokUpdates is the file Grok Build writes that session of that directory into, its durable UI
// record.
func grokUpdates(cwd, conversation string) string {
	return filepath.Join(grokSession(cwd, conversation), "updates.jsonl")
}

// grokClient is whether a process runs Grok Build's own client (orch.program names it `grok`).
func grokClient(words []string) bool {
	return agent.Program(words, false) == "grok"
}
