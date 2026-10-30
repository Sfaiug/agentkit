package seat

import (
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"
)

const testConfig = `[models.opus]
harness='claude'
model='claude-opus'
effort='xhigh'
provider='test'
[models.fable]
harness='claude'
model='claude-fable'
effort='xhigh'
provider='test'
[models.astra]
harness='codex'
model='gpt'
effort='xhigh'
provider='test'
[providers.test]
mode='subscription'
`

var moment = time.Unix(1_800_000_000, 0)

func sandbox(t *testing.T) string {
	t.Helper()
	home := t.TempDir()
	for key, value := range map[string]string{
		"HOME": home, "USERPROFILE": home, "TMUX_TMPDIR": t.TempDir(), "AGENTKIT_TMUX_SOCKET": "seat-test",
	} {
		t.Setenv(key, value)
	}
	write(t, filepath.Join(home, ".agentkit", "config.toml"), testConfig)
	return home
}

func write(t *testing.T, path, content string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
		t.Fatal(err)
	}
}

func encoded(t *testing.T, value any) string {
	t.Helper()
	data, err := json.Marshal(value)
	if err != nil {
		t.Fatal(err)
	}
	return string(data)
}

// record writes a seat's record, as a launch leaves one, with `fields` over it; a nil field
// is left out.
func record(t *testing.T, home, name string, fields map[string]any) {
	t.Helper()
	data := map[string]any{"orchestrator": "opus", "workers": []string{"opus"}, "cwd": filepath.Join(home, "work", name),
		"created": 1_799_000_000, "conversation": "conv-" + name, "id_source": "launcher", "resumable": true}
	for key, value := range fields {
		data[key] = value
		if value == nil {
			delete(data, key)
		}
	}
	write(t, filepath.Join(home, ".agentkit", "state", "session-"+name+".json"), encoded(t, data))
}

func runRecord(t *testing.T, home, name string, fields map[string]any) string {
	t.Helper()
	data := map[string]any{"run_id": name, "launched_session": "acme", "title": name}
	for key, value := range fields {
		data[key] = value
	}
	path := filepath.Join(home, ".agentkit", "runs", name, "run.json")
	write(t, path, encoded(t, data))
	if err := os.Chtimes(path, moment, moment); err != nil { // written as the clock reads
		t.Fatal(err)
	}
	return path
}

func transcript(t *testing.T, home, name, content string) {
	t.Helper()
	folder := projectFolder(filepath.Join(home, "work", name))
	write(t, filepath.Join(home, ".claude", "projects", folder, "conv-"+name+".jsonl"), content)
}

func TestHomesGoDoesNotKnow(t *testing.T) {
	merged := map[string]any{"state": "pass", "merged": true, "finished_at": 1_799_999_000}
	for name, build := range map[string]func(t *testing.T, home string){
		"a record not resumable": func(t *testing.T, home string) {
			record(t, home, "acme", map[string]any{"resumable": false})
		},
		"a record's lock beside it": func(t *testing.T, home string) {
			record(t, home, "acme", nil)
			write(t, filepath.Join(home, ".agentkit", "state", ".session-acme.lock"), "")
		},
		"a directory where a lock goes": func(t *testing.T, home string) {
			record(t, home, "acme", nil)
			if err := os.Mkdir(filepath.Join(home, ".agentkit", "state", "seat-acme.lock"), 0o700); err != nil {
				t.Fatal(err)
			}
		},
		"a seat file with a field no listing writes": func(t *testing.T, home string) {
			record(t, home, "acme", nil)
			write(t, filepath.Join(home, ".agentkit", "state", "seat-acme.json"), `{"stopped_at": 1}`)
		},
		"a merge with nothing running": func(t *testing.T, home string) {
			record(t, home, "acme", nil)
			runRecord(t, home, "r-merged", merged)
		},
		"a smoke run's merge with nothing running": func(t *testing.T, home string) {
			record(t, home, "acme", nil)
			runRecord(t, home, "r-merged", map[string]any{"state": "pass", "merged": true, "repo": filepath.Join(home, ".agentkit", "tmp", "smoke-1")})
		},
		"a pass not merged": func(t *testing.T, home string) {
			record(t, home, "acme", nil)
			runRecord(t, home, "r-going", map[string]any{"state": "running"})
			runRecord(t, home, "r-passed", map[string]any{"state": "pass"})
		},
		"an answer where the config offers a model with no effort": func(t *testing.T, home string) {
			write(t, filepath.Join(home, ".agentkit", "config.toml"), testConfig+"[models.bare]\nharness='claude'\nmodel='claude-bare'\nprovider='test'\n")
			record(t, home, "acme", nil)
			transcript(t, home, "acme", `{"type":"assistant","message":{"model":"claude-fable"}}`+"\n")
		},
	} {
		t.Run(name, func(t *testing.T) {
			home := sandbox(t)
			build(t, home)
			if _, known := Read(moment); known {
				t.Fatal("Read knows this home")
			}
		})
	}
}

// row is what a test reads of a seat, its reason being what the seat file gets.
type row struct{ Name, Project, Word, Tally, Orchestrator, Workers, reason string }

func rows(home Home) []row {
	var found []row
	for _, seat := range home.Seats {
		found = append(found, row{seat.Name, seat.Project, seat.Word, seat.Tally, seat.Orchestrator, seat.Workers, seat.reason})
	}
	return found
}

func TestHomesGoKnows(t *testing.T) {
	closed := "session closed: press 1 to reopen"
	for name, example := range map[string]struct {
		build func(t *testing.T, home string)
		want  []row
	}{
		"projects by name, those filed under none last, each by when it was made": {
			func(t *testing.T, home string) {
				for _, project := range []string{"alpha", "zeta"} {
					if err := os.MkdirAll(filepath.Join(home, "code", project, ".git"), 0o700); err != nil {
						t.Fatal(err)
					}
				}
				record(t, home, "a-zeta", map[string]any{"repo": filepath.Join(home, "code", "zeta"), "created": 1})
				record(t, home, "m-loose", map[string]any{"repo": filepath.Join(home, "elsewhere", "alpha"), "created": 2})
				record(t, home, "y-alpha", map[string]any{"repo": filepath.Join(home, "code", "alpha"), "created": 5})
				record(t, home, "z-alpha", map[string]any{"repo": filepath.Join(home, "code", "alpha"), "created": 4})
			},
			[]row{
				{"z-alpha", "alpha", "idle", "no runs yet", "opus", "opus", closed},
				{"y-alpha", "alpha", "idle", "no runs yet", "opus", "opus", "session closed: press 2 to reopen"},
				{"a-zeta", "zeta", "idle", "no runs yet", "opus", "opus", "session closed: press 3 to reopen"},
				{"m-loose", "alpha", "idle", "no runs yet", "opus", "opus", "session closed: press 4 to reopen"},
			},
		},
		"a running run whose record says it has not merged": {
			func(t *testing.T, home string) {
				record(t, home, "acme", nil)
				runRecord(t, home, "r-going", map[string]any{"state": "running", "merged": false, "title": "Beta"})
			},
			[]row{{"acme", "no project", "working", "1 running · 0 merged", "opus", "opus", "1 running · Beta"}},
		},
		"a Codex record with no conversation": {
			func(t *testing.T, home string) {
				record(t, home, "acme", map[string]any{"orchestrator": "astra", "workers": []string{"astra"}, "conversation": ""})
			},
			[]row{{"acme", "no project", "idle", "no runs yet", "astra", "astra", closed + " · starts a new Codex conversation"}},
		},
		"a Claude record with no conversation has no row": {
			func(t *testing.T, home string) { record(t, home, "acme", map[string]any{"conversation": ""}) },
			nil,
		},
		"a transcript with no answer": {
			func(t *testing.T, home string) {
				record(t, home, "acme", nil)
				transcript(t, home, "acme", `{"type":"assistant","message":{"model":"<synthetic>"}}`+"\n"+
					`{"type":"assistant","isSidechain":true,"message":{"model":"claude-fable"}}`+"\nnot JSON")
			},
			[]row{{"acme", "no project", "idle", "no runs yet", "opus", "opus", closed}},
		},
		"a last answer on the seat's own model and effort": {
			func(t *testing.T, home string) {
				record(t, home, "acme", nil)
				transcript(t, home, "acme", `{"type":"assistant","message":{"model":"claude-fable"}}`+"\n"+
					`{"type":"assistant","effort":"xhigh","message":{"model":"claude-opus"}}`+"\n")
			},
			[]row{{"acme", "no project", "idle", "no runs yet", "opus", "opus", closed}},
		},
		"a last answer on a model no entry runs": {
			func(t *testing.T, home string) {
				record(t, home, "acme", nil)
				transcript(t, home, "acme", `{"type":"assistant","message":{"model":"claude-nobody"}}`+"\n")
			},
			[]row{{"acme", "no project", "idle", "no runs yet", "opus", "opus", closed}},
		},
		"another conversation's transcript": {
			func(t *testing.T, home string) {
				record(t, home, "acme", nil)
				transcript(t, home, "other", `{"type":"assistant","message":{"model":"claude-fable"}}`+"\n")
			},
			[]row{{"acme", "no project", "idle", "no runs yet", "opus", "opus", closed}},
		},
		"a real merge beside a smoke suite's running run": {
			func(t *testing.T, home string) {
				record(t, home, "acme", nil)
				runRecord(t, home, "r-going", map[string]any{"state": "running", "repo": filepath.Join(home, ".agentkit", "tmp", "smoke-1")})
				runRecord(t, home, "r-merged", map[string]any{"state": "pass", "merged": true, "finished_at": 1_799_999_000})
			},
			[]row{{"acme", "no project", "idle", "0 running · 1 merged", "opus", "opus", closed}},
		},
		"the run gone quiet names the reason, though another started later": {
			func(t *testing.T, home string) {
				record(t, home, "acme", nil)
				quiet := runRecord(t, home, "a-quiet", map[string]any{"state": "running", "title": "Quiet run", "started_at": 2000})
				runRecord(t, home, "z-active", map[string]any{"state": "running", "title": "Active run", "started_at": 1000})
				if err := os.Chtimes(quiet, moment.Add(-2*time.Hour), moment.Add(-2*time.Hour)); err != nil {
					t.Fatal(err)
				}
			},
			[]row{{"acme", "no project", "working", "2 running · 0 merged", "opus", "opus", "2 running · silent 2h · Quiet run"}},
		},
		"the last started names the reason where none has gone quiet": {
			func(t *testing.T, home string) {
				record(t, home, "acme", nil)
				runRecord(t, home, "a-first", map[string]any{"state": "running", "title": "First", "started_at": 1000})
				runRecord(t, home, "z-second", map[string]any{"state": "running", "title": "Second", "started_at": 2000})
			},
			[]row{{"acme", "no project", "working", "2 running · 0 merged", "opus", "opus", "2 running · Second"}},
		},
		"workers Python's own check refuses": {
			func(t *testing.T, home string) {
				record(t, home, "acme", map[string]any{"workers": []string{"opus", "opus"}})
				transcript(t, home, "acme", `{"type":"assistant","message":{"model":"claude-fable"}}`+"\n")
			},
			[]row{{"acme", "no project", "idle", "no runs yet", "?", "?", closed}},
		},
	} {
		t.Run(name, func(t *testing.T) {
			home := sandbox(t)
			example.build(t, home)
			found, known := Read(moment)
			if !known {
				t.Fatal("Read does not know this home")
			}
			if got := rows(found); !reflect.DeepEqual(got, example.want) {
				t.Fatalf("rows:\n got %+v\nwant %+v", got, example.want)
			}
		})
	}
}

func TestAWorktreeIsFiledUnderTheCheckoutItWasAddedFrom(t *testing.T) {
	if _, err := exec.LookPath("git"); err != nil {
		t.Skip("no git")
	}
	home := sandbox(t)
	t.Setenv("GIT_CONFIG_GLOBAL", os.DevNull)
	main, added := filepath.Join(home, "code", "main"), filepath.Join(home, "elsewhere", "added")
	if err := os.MkdirAll(main, 0o700); err != nil {
		t.Fatal(err)
	}
	for _, args := range [][]string{{"init", "-q"}, {"-c", "user.name=acme", "-c", "user.email=acme@example.com", "commit", "-q", "--allow-empty", "-m", "start"}, {"worktree", "add", "-q", added}} {
		if out, err := exec.Command("git", append([]string{"-C", main}, args...)...).CombinedOutput(); err != nil {
			t.Fatalf("git %v: %v\n%s", args, err, out)
		}
	}
	if err := os.MkdirAll(filepath.Join(home, "code", "other", ".git"), 0o700); err != nil {
		t.Fatal(err)
	}
	record(t, home, "acme", map[string]any{"repo": added, "created": 5})
	record(t, home, "zed", map[string]any{"repo": filepath.Join(home, "code", "other"), "created": 1})
	found, known := Read(moment)
	if !known || len(found.Seats) != 2 || found.Seats[0].Name != "acme" || found.Seats[0].Project != "added" {
		t.Fatalf("known=%v seats=%+v", known, found.Seats)
	}
}

// What a seat's last answer ran on moves its record as `/model` and `/effort` typed in it do:
// to the model an entry runs, its own first, each model it then runs at its entry's efforts,
// and the answer's effort where that model takes it.
func TestAnnounceFollowsTheSeatsLastAnswer(t *testing.T) {
	entry := map[string]any{"effort": "xhigh"}
	for name, example := range map[string]struct {
		answer string
		want   map[string]any
	}{
		"another model": {`{"type":"assistant","message":{"model":"claude-fable"}}`,
			map[string]any{"orchestrator": "fable", "efforts": map[string]any{"fable": entry, "opus": entry}}},
		"another effort": {`{"type":"assistant","effort":"low","message":{"model":"claude-opus"}}`,
			map[string]any{"orchestrator": "opus", "efforts": map[string]any{"opus": map[string]any{"effort": "low", "exec_effort": "xhigh", "review_effort": "xhigh"}}}},
		"another model at an effort it takes": {`{"type":"assistant","effort":"max","message":{"model":"claude-fable"}}`,
			map[string]any{"orchestrator": "fable", "efforts": map[string]any{"fable": map[string]any{"effort": "max", "exec_effort": "xhigh", "review_effort": "xhigh"}, "opus": entry}}},
		"an effort the model does not take": {`{"type":"assistant","effort":"ultra","message":{"model":"claude-opus"}}`,
			map[string]any{"orchestrator": "opus"}},
		"the seat's own model and effort": {`{"type":"assistant","effort":"xhigh","message":{"model":"claude-opus"}}`,
			map[string]any{"orchestrator": "opus"}},
	} {
		t.Run(name, func(t *testing.T) {
			home := sandbox(t)
			record(t, home, "acme", map[string]any{"repo": nil})
			transcript(t, home, "acme", example.answer+"\n")
			found, known := Read(moment)
			if !known {
				t.Fatal("Read does not know this home")
			}
			if err := found.Announce(moment); err != nil {
				t.Fatal(err)
			}
			var got map[string]any
			data, err := os.ReadFile(filepath.Join(home, ".agentkit", "state", "session-acme.json"))
			if err != nil || json.Unmarshal(data, &got) != nil {
				t.Fatalf("record %q: %v", data, err)
			}
			if got["orchestrator"] != example.want["orchestrator"] || !reflect.DeepEqual(got["efforts"], example.want["efforts"]) {
				t.Fatalf("record %s", data)
			}
		})
	}
}

// A Claude record with no conversation has no row, but its listing still files it.
func TestAnnounceInfersARepoForASeatWithNoRow(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", map[string]any{"conversation": ""})
	found, known := Read(moment)
	if !known || found.Seatless() || len(found.Seats) != 0 {
		t.Fatalf("known=%v home=%+v", known, found)
	}
	if err := found.Announce(moment); err != nil {
		t.Fatal(err)
	}
	state := filepath.Join(home, ".agentkit", "state")
	data, err := os.ReadFile(filepath.Join(state, "session-acme.json"))
	if err != nil || !strings.Contains(string(data), `"repo": null`) {
		t.Fatalf("record %q: %v", data, err)
	}
	if _, err := os.Stat(filepath.Join(state, "seat-acme.json")); err == nil {
		t.Fatal("a seat with no row got a seat file")
	}
}

// What another screen published between this reading and its announcement stands: the word
// began when that screen says, under the announce lock, not when this reading saw another.
func TestAnnounceReadsTheSeatFileItDecidesFromUnderItsLock(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", map[string]any{"repo": nil})
	path := filepath.Join(home, ".agentkit", "state", "seat-acme.json")
	write(t, path, `{"word": "working", "word_since": 111}`)
	found, known := Read(moment)
	if !known {
		t.Fatal("Read does not know this home")
	}
	write(t, path, `{"word": "idle", "word_since": 222}`)
	if err := found.Announce(moment); err != nil {
		t.Fatal(err)
	}
	var seat map[string]any
	data, err := os.ReadFile(path)
	if err != nil || json.Unmarshal(data, &seat) != nil {
		t.Fatalf("seat file %q: %v", data, err)
	}
	if seat["word"] != "idle" || seat["word_since"] != float64(222) {
		t.Fatalf("seat file %v", seat)
	}
}

func TestAnUnchangedSeatFileIsNotWritten(t *testing.T) {
	home := sandbox(t)
	record(t, home, "acme", map[string]any{"repo": nil})
	path := filepath.Join(home, ".agentkit", "state", "seat-acme.json")
	// `unsent` null reads as no draft
	unchanged := `{"word": "idle", "reason": "session closed: press 1 to reopen", "unsent": null, "word_since": null, "word_from": [null, null, ""], "session": "acme"}`
	write(t, path, unchanged)
	found, known := Read(moment)
	if !known {
		t.Fatal("Read does not know this home")
	}
	if err := found.Announce(moment); err != nil {
		t.Fatal(err)
	}
	if data, err := os.ReadFile(path); err != nil || string(data) != unchanged {
		t.Fatalf("seat file %q: %v", data, err)
	}
}

func TestProjectFolderIsClaudeCodes(t *testing.T) {
	for cwd, want := range map[string]string{
		"/home/acme/code/fix-api":                "-home-acme-code-fix-api",
		"/home/acme/caf\u00e9/\U0001F680":        "-home-acme-caf----",
		"/home/acme/" + strings.Repeat("x", 210): "-home-acme-" + strings.Repeat("x", 189) + "-jum450",
		"/home/acme/" + strings.Repeat("\u00e9", 150) + strings.Repeat("\U0001F680", 40): "-home-acme-" + strings.Repeat("-", 189) + "-1yrcfo",
	} {
		if got := projectFolder(cwd); got != want {
			t.Fatalf("projectFolder(%q) = %q, want %q", cwd, got, want)
		}
	}
}
