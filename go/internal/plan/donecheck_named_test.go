package plan

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"agentkit/internal/notify"
	"agentkit/internal/run"
)

// A seat's current conversation is none of its own only on proof its harness named none yet: each
// file read for its name absent.  One there that is a folder, is not UTF-8 or says no name keeps
// the conversation, so a finished plan is never finished on it without an error, nor does a loose
// read of its conversations read it as having none.
func TestAFinishedPlanIsFinishedOnAnUnnamedConversationOnlyOnProof(t *testing.T) {
	token := strings.Repeat("a", 32)
	for harness, files := range map[string]int{"opencode": 1, "muse": 1, "codex": 2, "antigravity": 1} {
		for at := range files {
			for _, held := range []string{"nothing", "a folder", "not UTF-8", "no name"} {
				home := t.TempDir()
				t.Setenv("HOME", home)
				t.Setenv("USERPROFILE", home)
				t.Setenv("AGENTKIT_ADAPTER_DIR", "")
				state, cwd := filepath.Join(home, ".agentkit", "state"), filepath.Join(home, "acme")
				rollout := filepath.Join(home, "rollout.jsonl")
				// each file read on the way to the name, as it names one and as it names none
				type file struct{ path, names, malformed string }
				read := map[string][]file{
					"opencode":    {{filepath.Join(state, "opencode-launch-"+token, "session"), "ses_acme", "acme"}},
					"muse":        {{filepath.Join(state, "muse-launch-"+token, "session"), "acme-session", "not a session"}},
					"antigravity": {{filepath.Join(state, "session-other.json"), `{"orchestrator": "mid", "id_source": "launcher", "conversation": "c-acme"}`, `{"orchestrator": `}},
					"codex": {
						{filepath.Join(state, "codex-launch-"+token+".json"), run.Line(run.Fields("launch", token, "cwd", cwd, "event", run.Fields(
							"hook_event_name", "SessionStart", "source", "startup", "session_id", "acme-session", "transcript_path", rollout, "cwd", cwd))),
							`{"launch": `},
						{rollout, run.Line(run.Fields("type", "session_meta", "payload", run.Fields("id", "acme-session", "cwd", cwd))) + "\n",
							`{"type": "session_meta", "payload": `},
					},
				}[harness]
				write := func(path, text string) {
					t.Helper()
					if os.MkdirAll(filepath.Dir(path), 0o700) != nil || os.WriteFile(path, []byte(text), 0o600) != nil {
						t.Fatal(path)
					}
				}
				write(filepath.Join(home, ".agentkit", "config.toml"), "[models.mid]\nharness = '"+harness+
					"'\nmodel = 'acme/m'\neffort = 'high'\nprovider = 'test'\n[providers.test]\nmode = 'subscription'\n")
				write(filepath.Join(state, "plan-acme.md"), "- [x] Build the acme report.\n")
				write(filepath.Join(state, "session-acme.json"), run.Line(run.Fields("orchestrator", "mid", "cwd", cwd, harness+"_launch", token)))
				for _, before := range read[:at] {
					write(before.path, before.names)
				}
				switch path := read[at].path; held {
				case "a folder":
					os.MkdirAll(path, 0o700)
				case "not UTF-8":
					write(path, strings.Replace(read[at].names, "acme", "acme\xff", 1))
				case "no name":
					write(path, read[at].malformed)
				}
				finished, err := Finished("acme")
				had, loose := notify.Conversations("acme", false)
				unproven := held != "nothing" || harness == "antigravity" // a launch /proc may not show proves no absence
				if !unproven && (!finished || err != nil || len(had) != 0 || loose != nil) {
					t.Errorf("%s, file %d gone: finished %v, %v; %v, %v", harness, at, finished, err, had, loose)
				}
				if unproven && (finished && err == nil || len(had) == 0 && loose == nil) {
					t.Errorf("%s, file %d %s: finished %v, %v; read loosely %v, %v", harness, at, held, finished, err, had, loose)
				}
			}
		}
	}
}
