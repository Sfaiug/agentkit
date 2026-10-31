package cli

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"unicode/utf8"

	"agentkit/internal/box"
)

const testConfig = "[models.acme]\nharness='echo'\nmodel='echo-1'\neffort='low'\nprovider='test'\n[providers.test]\nmode='subscription'\n"

func sandbox(t *testing.T) string {
	t.Helper()
	home := t.TempDir()
	for key, value := range map[string]string{
		"HOME": home, "USERPROFILE": home, "AGENTKIT_SESSION": "", "AGENTKIT_RUN_DIR": "",
		"AK_RUN_DEPTH": "0", "AK_RUN_ROLE": "", "AK_FETCH_TIMEOUT": "0", "AK_HAND_IN": "",
	} {
		t.Setenv(key, value)
	}
	write(t, filepath.Join(home, ".agentkit", "config.toml"), testConfig)
	write(t, filepath.Join(home, "task.md"), "example\n")
	return home
}

func write(t *testing.T, path, content string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(content), 0600); err != nil {
		t.Fatal(err)
	}
}

func assertCall(t *testing.T, args []string, code int, stdout, stderr string) {
	t.Helper()
	home, _ := os.UserHomeDir()
	before := tree(t, home)
	var out, errOut bytes.Buffer
	got := Main(args, &out, &errOut)
	if got != code || out.String() != stdout || errOut.String() != stderr {
		t.Fatalf("%q: got (%d, %q, %q), want (%d, %q, %q)", args, got, out.String(), errOut.String(), code, stdout, stderr)
	}
	if !reflect.DeepEqual(before, tree(t, home)) {
		t.Fatalf("%q changed HOME", args)
	}
}

func TestResumeDepth(t *testing.T) {
	sandbox(t)
	for _, depth := range []string{"2", "3", "0002", "999999999999999999999"} {
		t.Setenv("AK_RUN_DEPTH", depth)
		for _, args := range [][]string{{"run", "resume", "nope"}, {"run", "resume"}, {"run", "task.md"}} {
			assertCall(t, args, 2, "", "a worker's worker may not start runs (depth "+strings.TrimLeft(depth, "0")+"); only the orchestrator, and a worker for its tests, may\n")
		}
	}
	for _, depth := range []string{"", "x", "-1"} {
		t.Setenv("AK_RUN_DEPTH", depth)
		assertCall(t, []string{"run", "resume", "nope"}, 2, "", "ak run: AK_RUN_DEPTH must be a non-negative integer\n")
	}
	t.Setenv("AK_RUN_DEPTH", "2")
	assertCall(t, []string{"run", "show"}, 3, "", "ak run: not implemented in Go yet\n")
}

func TestFetchInputRefusals(t *testing.T) {
	home := sandbox(t)
	for _, path := range []string{"", "a\nb", "a\tb", "a\rb", "a\x00b", "''", `""`, "   "} {
		assertCall(t, []string{"fetch", path}, 1, "", "ak fetch: a file path must be non-empty and contain no tabs or newlines\n")
	}
	task := filepath.Join(home, "task.md")
	assertCall(t, []string{"fetch", task, "''", "a\tb"}, 1, task+"\n", strings.Repeat("ak fetch: a file path must be non-empty and contain no tabs or newlines\n", 2))
	for _, timeout := range []string{"0x1p1", "0X1P1", "NaN", "inf", "-1", "1__0"} {
		t.Setenv("AK_FETCH_TIMEOUT", timeout)
		assertCall(t, []string{"fetch", task}, 2, "", "ak fetch: AK_FETCH_TIMEOUT must be a finite, non-negative number\n")
	}
	for _, timeout := range []string{"0", "-0.0", " 1_0.5e+2 ", ".5", "1."} {
		t.Setenv("AK_FETCH_TIMEOUT", timeout)
		assertCall(t, []string{"fetch", task}, 0, task+"\n", "")
	}
}

func TestConfigurationRefusals(t *testing.T) {
	home := sandbox(t)
	path := filepath.Join(home, ".agentkit", "config.toml")
	for _, example := range []struct{ data, reason string }{
		{"[defaults]\norchestrator='acme'\n", "missing [models] table"},
		{"[defaults]\nworkers='acme'\n" + testConfig, "[defaults].workers must list distinct model names (got 'acme')"},
		{"[defaults]\nworkers=['acme','acme']\n" + testConfig, "[defaults].workers must list distinct model names (got ['acme', 'acme'])"},
	} {
		write(t, path, example.data)
		for _, args := range [][]string{{"usage", "--json"}, {"models", "--json"}, {"worker", "acme", filepath.Join(home, "task.md")}, {"orch", "--dry-run"}} {
			assertCall(t, args, 2, "", "ak "+args[0]+": "+path+": "+example.reason+"\n")
		}
	}
	for _, data := range []string{"max_runs=1\nmax_runs=2\n", "x=[\n"} {
		write(t, path, data)
		for _, args := range [][]string{{"usage", "--json"}, {"models", "--json"}, {"worker", "acme", filepath.Join(home, "task.md")}, {"orch", "--dry-run"}} {
			before := tree(t, home)
			var out, errOut bytes.Buffer
			if code := Main(args, &out, &errOut); code != 2 || out.Len() != 0 || !strings.HasPrefix(errOut.String(), "ak "+args[0]+": "+path+": ") {
				t.Fatalf("configuration refusal: %d %q %q", code, out.String(), errOut.String())
			}
			if !reflect.DeepEqual(before, tree(t, home)) {
				t.Fatal("configuration refusal changed HOME")
			}
		}
	}
}

func TestWorkerModelRefusals(t *testing.T) {
	home := sandbox(t)
	assertCall(t, []string{"worker", "nosuch", filepath.Join(home, "task.md")}, 2, "", "ak worker: unknown model 'nosuch'; ~/.agentkit/config.toml defines: acme\n")
	// a home naming no folder of adapters, as every real one, leaves its turn to Python
	t.Setenv("AGENTKIT_ADAPTER_DIR", "")
	assertCall(t, []string{"worker", "acme", filepath.Join(home, "task.md")}, 3, "", "ak worker: not implemented in Go yet\n")
	adapters := t.TempDir()
	t.Setenv("AGENTKIT_ADAPTER_DIR", adapters)
	code, said := 2, "ak worker: no adapter for harness 'echo': "+filepath.Join(adapters, "echo.sh")+" does not exist\n"
	if !box.Supported {
		code, said = 3, "ak worker: not implemented in Go yet\n"
	}
	var out, errOut bytes.Buffer
	if got := Main([]string{"worker", "acme", filepath.Join(home, "task.md")}, &out, &errOut); got != code || out.Len() != 0 || errOut.String() != said {
		t.Fatalf("got (%d, %q, %q), want (%d, \"\", %q)", got, out.String(), errOut.String(), code, said)
	}
}

func TestNotifyNeeds(t *testing.T) {
	home := sandbox(t)
	ask := func(args ...string) []string { return append([]string{"notify", "needs"}, args...) }
	unimplemented := "ak notify needs: not implemented in Go yet\n"
	assertCall(t, ask("Which branch?"), 2, "", "ak notify: notify needs a session: use --session NAME\n")
	// a watch record leaves the seat's word, and so the ask, to Python
	write(t, filepath.Join(home, ".agentkit", "state", "watch.json"), "{}")
	assertCall(t, ask("Which branch?", "--session", "acme"), 3, "", unimplemented)
	// a seat asking for itself is its turn's to decide, before its record is read
	t.Setenv("AGENTKIT_SESSION", "acme")
	write(t, filepath.Join(home, ".agentkit", "state", "session-acme.json"), "{")
	for _, args := range [][]string{ask("Which branch?"), ask("Which branch?", "--dry-run"), ask("Which branch?", "--session", " acme"), ask("Which branch?", "--session", "acme", "--dry-run")} {
		assertCall(t, args, 3, "", unimplemented)
	}
	write(t, filepath.Join(home, ".agentkit", "state", "session-acme.json"), `{"renamed": "acme-2"}`)
	assertCall(t, ask("Which branch?", "--session", "acme-2", "--dry-run"), 3, "", unimplemented)
	// Python's json.dumps(page, indent=2): its keys' order, past ASCII escaped, nothing HTML-escaped
	t.Setenv("AGENTKIT_DISCORD_USER_ID", " <4\"2>\n")
	page := `{
  "username": "agentkit",
  "content": "\ud83d\ude4b Needs you \u00b7 caf\u00e9 <@<4\"2>>",
  "allowed_mentions": {
    "users": [
      "<4\"2>"
    ]
  }
}
`
	notice := "Needs you · café: Which branch? It"
	notice += strings.Repeat("x", 1000-utf8.RuneCountInString(notice))
	assertCall(t, ask("Which\tbranch?\u200b\u200bIt"+strings.Repeat("x", 1000), "--session", "café", "--dry-run"), 0, page, "terminal notice: "+notice+"\n")
	// what Go cannot read is Python's
	t.Setenv("AGENTKIT_DISCORD_USER_ID", "")
	write(t, filepath.Join(home, ".agentkit", "secrets", "discord_user_id", "id"), "42\n")
	for _, args := range [][]string{ask("Which branch?\xff", "--session", "fix", "--dry-run"), ask("Which branch?", "--session", "fix\xff", "--dry-run"), ask("Which branch?", "--session", "fix", "--dry-run")} {
		assertCall(t, args, 3, "", unimplemented)
	}
	// a worker's dry run says why it asks nothing, and logs nothing
	t.Setenv("AK_RUN_ROLE", "worker")
	t.Setenv("AK_RUN_LOG", filepath.Join(home, "run.log"))
	assertCall(t, ask("no question", "--dry-run"), 0, "notify: needs suppressed: AK_RUN_ROLE=worker; only an orchestrator may notify\n", "")
}

func TestPlanInputRefusals(t *testing.T) {
	home := sandbox(t)
	t.Setenv("AGENTKIT_SESSION", "acme")
	for _, outcome := range []string{"", " \t", "the parser · works"} {
		assertCall(t, []string{"plan", "add", outcome, "--check", "false"}, 2, "", "ak plan: an outcome is plain words without `·`\n")
	}
	assertCall(t, []string{"plan", "add", "the parser works", "--check", "false\nfalse"}, 2, "", "ak plan: acme is filed under no project; run `ak orch project <checkout>` first\n")
	write(t, filepath.Join(home, ".git"), "gitdir: ./git\n")
	data, err := json.Marshal(map[string]string{"repo": home})
	if err != nil {
		t.Fatal(err)
	}
	write(t, filepath.Join(home, ".agentkit", "state", "session-acme.json"), string(data))
	for _, command := range []string{"", "false\nfalse", "echo `false`", "false\u2028false"} {
		assertCall(t, []string{"plan", "add", "the parser works", "--check", command}, 2, "", "ak plan: a check is one shell command without backticks or line breaks\n")
		assertCall(t, []string{"plan", "check", "1", command}, 2, "", "ak plan: a check is one shell command without backticks or line breaks\n")
	}
	write(t, filepath.Join(home, ".agentkit", "state", "session-old.json"), `{"renamed":"middle"}`)
	write(t, filepath.Join(home, ".agentkit", "state", "session-middle.json"), `{"renamed":"  acme  "}`)
	write(t, filepath.Join(home, ".agentkit", "state", "session-acme-seat.json"), string(data))
	write(t, filepath.Join(home, ".agentkit", "state", "session-literal seat.json"), string(data))
	for _, name := range []string{"old", "  acme  ", "\u2003acme\t", "  acme   seat  ", " literal  seat "} {
		t.Setenv("AGENTKIT_SESSION", name)
		assertCall(t, []string{"plan", "add", "the parser works", "--check", "false\nfalse"}, 2, "", "ak plan: a check is one shell command without backticks or line breaks\n")
		// each name reaches the seat's project: the check naming it is refused before it runs
		assertCall(t, []string{"plan", "add", "the parser works", "--check", "cat " + home + "/x"}, 2, "", "ak plan: this check holds ~/., the path of the project's checkout, but a check runs in a clean checkout of its default branch: name paths relative to the repository, as in `python3 tests/test_x.py`\n")
		assertCall(t, []string{"run", filepath.Join(home, "task.md"), "--exec", "acme"}, 2, "", "ak run: --exec: not a seat's; ak picks the models, decides what goes first and refuses a second run of a change under way, so launch without\n")
	}
}

func TestHandInEvidenceRefusals(t *testing.T) {
	home := sandbox(t)
	turn := filepath.Join(home, "turn.jsonl")
	t.Setenv("AK_HAND_IN", turn)
	setTurn := func(role string, findings []map[string]any) {
		if findings == nil {
			findings = []map[string]any{}
		}
		data, err := json.Marshal(map[string]any{"kind": "turn", "role": role, "workspace": home, "findings": findings})
		if err != nil {
			t.Fatal(err)
		}
		write(t, turn, string(data)+"\n")
	}
	setTurn("reviewer", nil)
	for _, example := range []struct {
		args   []string
		reason string
	}{
		{[]string{"finding", "nonsense", "Wrong result", "Breaks callers", "--quote", "example"}, "name the location as path:line with a numeric line"},
		{[]string{"finding", "missing.py:1", "Wrong result", "Breaks callers", "--quote", "example"}, "name a file that exists inside this checkout"},
		{[]string{"finding", "task.md:99", "Wrong result", "Breaks callers", "--quote", "example"}, "choose a line from 1 to 1 in task.md"},
		{[]string{"finding", "task.md:1", "Wrong result", "Breaks callers", "--quote", "absent"}, "use a quote found verbatim in the named file"},
		{[]string{"follow-up", "task.md:1", "Wrong result", "Breaks callers", "--run", "false\nfalse"}, "write a follow-up's --run as one shell command, without backticks, line breaks or this checkout's path: it becomes a plan check"},
		{[]string{"follow-up", "task.md:1", "Wrong result", "Breaks callers", "--run", "false " + home}, "write a follow-up's --run as one shell command, without backticks, line breaks or this checkout's path: it becomes a plan check"},
	} {
		assertCall(t, append([]string{"hand-in"}, example.args...), 2, "", "ak hand-in: "+example.reason+"\n")
	}
	setTurn("fixer", nil)
	assertCall(t, []string{"hand-in", "dispute", "task.md:1", "Correct"}, 2, "", "ak hand-in: dispute must name a blocking finding handed to this turn; you may dispute: none\n")
	setTurn("fixer", []map[string]any{{"path": "task.md", "line": 1, "what": "Wrong result"}})
	assertCall(t, []string{"hand-in", "dispute", "task.md:1", "Correct"}, 2, "", "ak hand-in: supply evidence with exactly one of --run COMMAND or --quote LINES\n")
	assertCall(t, []string{"hand-in", "dispute", "task.md:1", "Correct", "--quote", "absent"}, 2, "", "ak hand-in: use a quote found verbatim in the named file\n")
	if err := os.Remove(filepath.Join(home, "task.md")); err != nil {
		t.Fatal(err)
	}
	assertCall(t, []string{"hand-in", "dispute", "task.md:1", "Correct", "--run", "false"}, 2, "", "ak hand-in: a dispute's command must exit 0 to show the behaviour is right\n")
}

func TestRunRecognizesJobs(t *testing.T) {
	home := sandbox(t)
	job := filepath.Join(home, ".agentkit", "jobs", "batch", "job.json")
	write(t, job, `{"job_id":"batch","tasks":[],"state":"pass"}`)
	for _, args := range [][]string{
		{"run", "status", "batch", "--json"},
		{"run", "show", "batch", "--json"},
		{"run", "stop", "batch"},
		{"run", "stop", "batch", "--keep"},
	} {
		suffix := ""
		if args[1] != "show" {
			suffix = " " + args[1]
		}
		assertCall(t, args, 3, "", "ak run"+suffix+": not implemented in Go yet\n")
	}
}
