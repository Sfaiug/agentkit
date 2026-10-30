package handin

import (
	"errors"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"testing"
)

// checkout is a checkout holding api.py, and the record file AK_HAND_IN names.
func checkout(t *testing.T) (string, string) {
	t.Helper()
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "api.py"), []byte("def get():\n    return None\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	record := filepath.Join(t.TempDir(), "hand-in.jsonl")
	t.Setenv("AK_HAND_IN", record)
	return dir, record
}

// opened is the turn row a checkout's record file opens with, with the members rest adds.
func opened(dir, rest string) string {
	return `{"kind": "turn", "workspace": ` + strconv.Quote(dir) + rest + "}\n"
}

// handIn hands args in to a record file of these lines, and answers what it appended.
func handIn(t *testing.T, record, lines string, args ...string) (string, error) {
	t.Helper()
	if err := os.WriteFile(record, []byte(lines), 0o600); err != nil {
		t.Fatal(err)
	}
	err := Hand(args)
	data, _ := os.ReadFile(record)
	if !strings.HasPrefix(string(data), lines) {
		t.Fatalf("%q rewrote the record: %q", args, data)
	}
	return string(data[len(lines):]), err
}

func TestRowsAreWrittenAsPythonWritesThem(t *testing.T) {
	if _, err := exec.LookPath("bash"); err != nil {
		t.Skip("proofs run in bash")
	}
	ws, record := checkout(t)
	t.Setenv("AK_HAND_IN_CONTINUE", "1")
	handed := opened(ws, `, "role": "fixer", "findings": [{"path": "api.py", "line": 2, "what": "w\u00e9", "evidence": {"run": "false"}, "n": 1E5, "m": -0.0, "nan": NaN, "z": [true, null, "\ud83d\ude00"], "n": 2}]`)
	for _, example := range []struct {
		lines string
		args  []string
		row   string
	}{
		{opened(ws, ""),
			[]string{"finding", "api.py:2", "caf\u00e9 \U0001f600", "y", "--run", `printf 'bad \377\r\n'; echo ${AK_HAND_IN_CONTINUE:-unset}; kill -9 $$`},
			`{"kind": "finding", "path": "api.py", "line": 2, "what": "caf\u00e9 \ud83d\ude00", "why": "y", "evidence": {"run": "printf 'bad \\377\\r\\n'; echo ${AK_HAND_IN_CONTINUE:-unset}; kill -9 $$", "returncode": -9, "output": "bad \ufffd\r\nunset\n"}}`},
		{opened(ws, `, "role": "reviewer-pr"`),
			[]string{"follow-up", "./api.py:01", "x", "y", "--run", "true", "--before", "HEAD"},
			`{"kind": "follow-up", "path": "api.py", "line": 1, "what": "x", "why": "y", "evidence": {"run": "true", "returncode": 0, "output": ""}, "before": "HEAD"}`},
		{strings.TrimSuffix(opened(ws, `, "role": "executor"`), "\n") + "\r\n",
			[]string{"blocked", " \x1c caf\u00e9 \u2028\t"},
			`{"kind": "blocked", "why": "caf\u00e9"}`},
		{handed,
			[]string{"dispute", "api.py:2", "no", "--quote", "return None"},
			`{"kind": "dispute", "path": "api.py", "line": 2, "what": "w\u00e9", "why": "no", "evidence": {"quote": "return None"}, "finding": {"path": "api.py", "line": 2, "what": "w\u00e9", "evidence": {"run": "false"}, "n": 2, "m": -0.0, "nan": NaN, "z": [true, null, "\ud83d\ude00"]}}`},
		{handed + `{"kind": "dispute", "path": "api.py", "line": 2}` + "\n", []string{"done"}, `{"kind": "done"}`},
	} {
		if row, err := handIn(t, record, example.lines, example.args...); err != nil || row != example.row+"\n" {
			t.Errorf("%q appended %q (%v), want %q", example.args, row, err, example.row)
		}
	}
}

func TestWhatGoCannotReadAsPythonIsLeftToIt(t *testing.T) {
	ws, record := checkout(t)
	handed := opened(ws, `, "role": "fixer", "findings": [{"path": "api.py", "line": 2, "what": "w", "evidence": {"run": "false"}}]`)
	for _, example := range []struct {
		lines string
		args  []string
	}{
		{handed, []string{"done"}}, // its finding's proof runs again under the worker's limits
		{handed + "{\"kind\": \"note\", \"what\": \"\xff\"}\n", []string{"blocked", "why"}},
		{`{"kind": "turn", "workspace": "\ud800"}` + "\n", []string{"blocked", "why"}},
		{handed, []string{"blocked", "why \xff"}},
		{opened(ws, ""), []string{"finding", "api.py:\u0662", "x", "y", "--quote", "return None"}},
		{opened(ws, ", \"n\": "+strings.Repeat("1", 641)), []string{"blocked", "why"}}, // as PYTHONINTMAXSTRDIGITS says
		{opened(ws, ", \"n\": "+strings.Repeat("[", 501)+strings.Repeat("]", 501)), []string{"blocked", "why"}},
		{opened(ws, ""), []string{"finding", "api.py:" + strings.Repeat("0", 640) + "1", "x", "y", "--quote", "return None"}},
	} {
		if row, err := handIn(t, record, example.lines, example.args...); !errors.Is(err, ErrPython) || row != "" {
			t.Errorf("%q appended %q (%v), want it left to Python", example.args, row, err)
		}
	}
}

func TestSitesFollowLinksBeforeTheirParents(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("Python takes each .. away first on Windows")
	}
	ws, record := checkout(t)
	outside := t.TempDir()
	for _, dir := range []string{filepath.Join(ws, "real", "inner"), filepath.Join(outside, "inner")} {
		if err := os.MkdirAll(dir, 0o700); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.WriteFile(filepath.Join(ws, "real", "api.py"), []byte("right = True\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(outside, "api.py"), []byte("right = True\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink("real/inner", filepath.Join(ws, "link")); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(filepath.Join(outside, "inner"), filepath.Join(ws, "out")); err != nil {
		t.Fatal(err)
	}
	for _, example := range []struct{ workspace, site, path string }{
		{ws, "link/../api.py:1", "real/api.py"},
		{ws, ws + "/link/../api.py:1", "real/api.py"},
		{ws + "/link/..", "api.py:1", "api.py"},
		{ws, "out/../api.py:1", ""},
	} {
		row, err := handIn(t, record, opened(example.workspace, ""), "finding", example.site, "x", "y", "--quote", "right")
		want := `{"kind": "finding", "path": "` + example.path + `", "line": 1, "what": "x", "why": "y", "evidence": {"quote": "right"}}` + "\n"
		if example.path == "" && (row != "" || err == nil || err.Error() != "name a file that exists inside this checkout") {
			t.Errorf("%s in %s appended %q (%v), want it refused", example.site, example.workspace, row, err)
		} else if example.path != "" && (err != nil || row != want) {
			t.Errorf("%s in %s appended %q (%v), want %q", example.site, example.workspace, row, err, want)
		}
	}
}

func TestAMissingCurrentDirectoryIsLeftToPython(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("Windows removes no current directory")
	}
	ws, record := checkout(t)
	cwd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	gone := t.TempDir()
	if err := os.Chdir(gone); err != nil {
		t.Fatal(err)
	}
	defer os.Chdir(cwd)
	if err := os.Remove(gone); err != nil {
		t.Fatal(err)
	}
	site := filepath.Join(ws, "api.py") + ":1"
	if row, err := handIn(t, record, `{"kind": "turn", "workspace": "."}`+"\n", "finding", site, "x", "y", "--quote", "return None"); !errors.Is(err, ErrPython) || row != "" {
		t.Errorf("a workspace of . without a current directory appended %q (%v), want it left to Python", row, err)
	}
}

func TestQuotesAreFoundInPythonsTextView(t *testing.T) {
	ws, record := checkout(t)
	for _, example := range []struct{ data, quote string }{
		{"first\r\nsecond\r\n", "first\nsecond"},
		{"first\rsecond\r", "first\nsecond"},
		{"first\r\nsecond\rthird\n", "second\nthird"},
		{"bad \xff\xff\n", "bad \ufffd\ufffd"},
		{"bad \xe2\x82", "bad \ufffd"},
		{"bad \xe2\x82!\n", "bad \ufffd!"},
		{"bad \xe0\x80\x80\n", "bad \ufffd\ufffd\ufffd"},
		{"bad \xed\xa0\x80\n", "bad \ufffd\ufffd\ufffd"},
		{"bad \xf0\x9f\x92", "bad \ufffd"},
		{"valid \ufffd\U0001f600\r\n", "valid \ufffd\U0001f600"},
	} {
		if err := os.WriteFile(filepath.Join(ws, "task.md"), []byte(example.data), 0o600); err != nil {
			t.Fatal(err)
		}
		if _, err := handIn(t, record, opened(ws, ""), "finding", "task.md:1", "Wrong result", "Breaks callers", "--quote", example.quote); err != nil {
			t.Errorf("%q in %q: %v", example.quote, example.data, err)
		}
	}
}
