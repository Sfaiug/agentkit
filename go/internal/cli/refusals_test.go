package cli

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
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
	assertCall(t, []string{"run", "status"}, 3, "", "ak run status: not implemented in Go yet\n")
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
	assertCall(t, []string{"worker", "acme", filepath.Join(home, "task.md")}, 3, "", "ak worker: not implemented in Go yet\n")
}

func TestNotifySessionRefusal(t *testing.T) {
	sandbox(t)
	assertCall(t, []string{"notify", "needs", "Which branch?"}, 2, "", "ak notify: notify needs a session: use --session NAME\n")
	for _, flags := range [][]string{{"--dry-run"}, {"--session", "acme"}} {
		assertCall(t, append([]string{"notify", "needs", "Which branch?"}, flags...), 3, "", "ak notify needs: not implemented in Go yet\n")
	}
	t.Setenv("AGENTKIT_SESSION", "acme")
	assertCall(t, []string{"notify", "needs", "Which branch?"}, 3, "", "ak notify needs: not implemented in Go yet\n")
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
}

func TestHandInEvidenceRefusals(t *testing.T) {
	home := sandbox(t)
	turn := filepath.Join(home, "turn.jsonl")
	t.Setenv("AK_HAND_IN", turn)
	setTurn := func(role string, findings []finding) {
		if findings == nil {
			findings = []finding{}
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
	assertCall(t, []string{"hand-in", "finding", "task.md:1", "Wrong result", "Breaks callers", "--quote", "example"}, 3, "", "ak hand-in finding: not implemented in Go yet\n")
	setTurn("fixer", nil)
	assertCall(t, []string{"hand-in", "dispute", "task.md:1", "Correct"}, 2, "", "ak hand-in: dispute must name a blocking finding handed to this turn; you may dispute: none\n")
	setTurn("fixer", []finding{{Path: "task.md", Line: 1, What: "Wrong result"}})
	assertCall(t, []string{"hand-in", "dispute", "task.md:1", "Correct"}, 2, "", "ak hand-in: supply evidence with exactly one of --run COMMAND or --quote LINES\n")
	assertCall(t, []string{"hand-in", "dispute", "task.md:1", "Correct", "--quote", "absent"}, 2, "", "ak hand-in: use a quote found verbatim in the named file\n")
	if err := os.Remove(filepath.Join(home, "task.md")); err != nil {
		t.Fatal(err)
	}
	assertCall(t, []string{"hand-in", "dispute", "task.md:1", "Correct", "--run", "false"}, 3, "", "ak hand-in dispute: not implemented in Go yet\n")
}

func TestStatusRecognizesJobs(t *testing.T) {
	home := sandbox(t)
	job := filepath.Join(home, ".agentkit", "jobs", "batch", "job.json")
	write(t, job, `{"job_id":"batch","tasks":[],"state":"pass"}`)
	for _, command := range []string{"status", "show"} {
		suffix := ""
		if command == "status" {
			suffix = " status"
		}
		assertCall(t, []string{"run", command, "batch", "--json"}, 3, "", "ak run"+suffix+": not implemented in Go yet\n")
	}
}
