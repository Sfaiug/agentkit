//go:build unix

package tick

import (
	"bytes"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentkit/internal/run"
)

func TestSavedForeignPRIsFollowedAfterSearchDropsIt(t *testing.T) {
	ak, _ := goneHome(t) // a resting seat, whose readings take watch.json too
	path := filepath.Join(ak, "runs", "fix-api", "run.json")
	text := `{"state":"pass","foreign":true,"pr":"https://github.com/other/api/pull/1","handed_back":true,"reported":true,"tree_stopped":[null,null]}`
	put(t, path, text)
	for range 2 { // the second tick, and its seat readings, read watch.json following it
		if !carries(io.Discard, io.Discard) {
			t.Fatal("a saved foreign PR the open search no longer finds was handed over")
		}
	}
	if read(t, path) != text {
		t.Fatal("following it changed the settled run")
	}
	if own, _ := watched(t, ak)["own"].(map[string]any); own["https://github.com/other/api/pull/1"] == nil {
		t.Fatalf("watch.json follows %v", own)
	}
}

// forkSeat is a home whose lead seat, born at 1000 on a harness Go types into, sits at its empty
// prompt, gh finding no pull request open and viewing one as $HOME/view says.  The fake tmux keeps
// each key in $HOME/keys, and text typed while $HOME/jam names a file leaves that file a link to
// nowhere, which no lock can be taken on.
func forkSeat(t *testing.T) (ak, home string) {
	t.Helper()
	ak, _ = idleHome(t, `case "$*" in *"pr view"*) cat "$HOME/view" ;; *) echo '{"items": []}' ;; esac`)
	home = filepath.Dir(ak)
	bin := t.TempDir()
	draw := `printf '────────\n❯%s\n────────\n  ⏵⏵ bypass permissions on (shift+tab to cycle)\n'`
	put(t, filepath.Join(bin, "tmux"), `#!/bin/sh
case "$*" in
  *list-sessions*session_created*) printf 'lead\t1\t1000\n' ;;
  *list-sessions*) printf 'lead\t1\n' ;;
  *list-panes*) echo '%1 0' ;;
  *capture-pane*) cat "$HOME/shown" ;;
  *display-message*'#{pane_id}'*) printf '%%1\t1000\n' ;;
  *send-keys*)
    for last do :; done
    printf '%s\n' "$last" >> "$HOME/keys"
    if [ "$last" = Enter ]; then `+draw+` "" > "$HOME/shown"; else
      `+draw+` " $last" > "$HOME/shown"
      [ ! -e "$HOME/jam" ] || ln -sfn missing/lock "$(cat "$HOME/jam")"
    fi ;;
esac
`)
	if err := os.Chmod(filepath.Join(bin, "tmux"), 0o700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
	put(t, filepath.Join(ak, "config.toml"), "[audit]\non = false\n[models.opus]\nharness = 'claude'\nmodel = 'claude-opus'\neffort = 'xhigh'\nprovider = 'test'\n"+
		"[providers.test]\nmode = 'subscription'\n")
	put(t, filepath.Join(ak, "state", "session-lead.json"), `{"orchestrator": "opus", "workers": ["opus"], "conversation": "conv-lead", "cwd": "`+home+`"}`)
	put(t, filepath.Join(home, "shown"), "────────\n❯\n────────\n  ⏵⏵ bypass permissions on (shift+tab to cycle)\n")
	return ak, home
}

// A run that opened a PR from a fork hears what the maintainer decided once, in its seat: an
// approval stays the tick's own, a request for changes and a close go on the run and into the
// seat, and a line whose Enter a killed tick never pressed gets its Enter and no second copy.
func TestAForkPRsChangesRequestAndCloseAreSaidOnce(t *testing.T) {
	ak, home := forkSeat(t)
	address := "https://github.com/acme/widgets/pull/7"
	dir := filepath.Join(ak, "runs", "20261107-0900-add-retry-file")
	put(t, filepath.Join(dir, "run.json"), run.Line(run.Fields("state", "pass", "title", "Add retry file", "foreign", true, "pr", address,
		"launched_session", "lead", "merge_note", "waiting for the maintainer")))
	opening := "# NOT MERGED (1 of 3) — Add retry file\nWhy: waiting for the maintainer\nNext: read the result\n\nmerge: waiting for the maintainer\n"
	put(t, filepath.Join(dir, "result.md"), opening)
	state, _ := loadState()
	// tick is one outgoing pass with the maintainer's word in gh's answer, and what it said
	tick := func(view string, left error) string {
		t.Helper()
		put(t, filepath.Join(home, "view"), view)
		var said bytes.Buffer
		if err := (&ticking{state: state, log: newLog(&said, io.Discard), clock: time.Now}).outgoing("beta"); !errors.Is(err, left) {
			t.Fatalf("the pass ended %v, not %v, saying %q", err, left, said.String())
		}
		return said.String()
	}
	keys := func() string {
		typed, _ := os.ReadFile(filepath.Join(home, "keys"))
		return string(typed)
	}
	followed := func() *run.Object { return state.Dict("own").Dict(address) }
	record := func() *run.Object {
		record, _ := run.Read(dir)
		return record
	}
	notice := func(text string) string {
		return text + " -- " + address + ". Nothing was posted to Discord; this is the maintainer's decision on a PR of ours, for you to act on or not."
	}

	before := read(t, filepath.Join(dir, "run.json"))
	changes := "PR #7 Add retry file: the maintainer requested changes"
	asked := `{"state": "OPEN", "reviewDecision": "CHANGES_REQUESTED", "title": "Add retry file", "number": 7}`
	// a seat on a harness Go does not type into is Python's, with nothing written
	seated := read(t, filepath.Join(ak, "state", "session-lead.json"))
	put(t, filepath.Join(ak, "state", "session-lead.json"), strings.Replace(seated, `"opus"`, `"vela"`, 1))
	tick(asked, errLeft)
	if state.Dict("own").Has(address) || read(t, filepath.Join(dir, "run.json")) != before || keys() != "" {
		t.Fatalf("handed to Python after writing: %s, %q", run.Line(state), keys())
	}
	put(t, filepath.Join(ak, "state", "session-lead.json"), seated)

	if said := tick(`{"state": "OPEN", "reviewDecision": "APPROVED", "title": "Add retry file", "number": 7}`, nil); said != "" ||
		followed().Get("decision") != "APPROVED" || !followed().Truthy("decision_at") || followed().Str("session") != "lead" {
		t.Fatalf("the approval was followed as %s, saying %q", run.Line(followed()), said)
	}
	if read(t, filepath.Join(dir, "run.json")) != before || keys() != "" {
		t.Fatalf("an approval reached the run or its seat: %q", keys())
	}

	// a tick killed between the line and its Enter left the decision on the run, the line in the
	// composer and its mark on the run, and watch.json as it was
	result := opening + "\n## The maintainer decided\n\n" + changes + "\n"
	put(t, filepath.Join(dir, "result.md"), result)
	put(t, filepath.Join(dir, "run.json"), run.Line(run.Fields("state", "pass", "title", "Add retry file", "foreign", true, "pr", address,
		"launched_session", "lead", "merge_note", changes, "decision_typed", run.Fields("line", notice(changes), "seat", 1000))))
	put(t, filepath.Join(home, "shown"), "────────\n❯ "+notice(changes)+"\n────────\n  ⏵⏵ bypass permissions on (shift+tab to cycle)\n")
	if said := tick(asked, nil); said != "" || keys() != "Enter\n" || followed().Get("decision") != "APPROVED" || !record().Truthy("decision_typed") {
		t.Fatalf("the line left in the composer was not given its Enter alone: %q, saying %q", keys(), said)
	}
	if said := tick(asked, nil); said != "told the lead seat: "+changes+"\n" || keys() != "Enter\n" ||
		followed().Get("decision") != "CHANGES_REQUESTED" || record().Has("decision_typed") {
		t.Fatalf("the sent line was not settled: %q, saying %q, the run %s", keys(), said, run.Line(record()))
	}
	settled := read(t, filepath.Join(dir, "run.json"))
	if said := tick(asked, nil); said != "" || keys() != "Enter\n" || read(t, filepath.Join(dir, "result.md")) != result ||
		read(t, filepath.Join(dir, "run.json")) != settled {
		t.Fatalf("the request for changes was handed on again: %q, saying %q", keys(), said)
	}

	closed := "PR #7 Add retry file: closed by the maintainer without a merge"
	shut := `{"state": "CLOSED", "reviewDecision": "CHANGES_REQUESTED", "title": "Add retry file", "number": 7}`
	if said := tick(shut, nil); said != "recorded on run "+filepath.Base(dir)+": "+closed+"\ntold the lead seat: "+closed+"\n" ||
		keys() != "Enter\n"+notice(closed)+"\nEnter\n" || !followed().Truthy("done") || record().Str("merge_note") != closed ||
		record().Has("decision_typed") {
		t.Fatalf("the close was handed on as %q, saying %q, the run %s", keys(), said, run.Line(record()))
	}
	if got := read(t, filepath.Join(dir, "result.md")); got != result+"\n## The maintainer decided\n\n"+closed+"\n" {
		t.Fatalf("result.md holds %q", got)
	}
	settled = read(t, filepath.Join(dir, "run.json"))
	if said := tick(shut, nil); said != "" || strings.Count(keys(), "Enter") != 2 || read(t, filepath.Join(dir, "run.json")) != settled {
		t.Fatalf("a closed PR was followed again: %q, saying %q", keys(), said)
	}
}

// A line whose mark cannot be kept on the run gets no Enter and fails the pass, as Python's raise
// does, so no tick sends a second copy: it waits in the composer, a draft no later tick types past,
// whether the run held no mark or one an earlier copy left before the seat was reopened.
func TestADecisionWhoseMarkCannotBeWrittenIsNeverSentTwice(t *testing.T) {
	address := "https://github.com/acme/widgets/pull/7"
	for decided, view := range map[string]string{
		"the maintainer requested changes":         `{"state": "OPEN", "reviewDecision": "CHANGES_REQUESTED", "title": "Add retry file", "number": 7}`,
		"closed by the maintainer without a merge": `{"state": "CLOSED", "reviewDecision": "", "title": "Add retry file", "number": 7}`,
	} {
		line := "PR #7 Add retry file: " + decided + " -- " + address +
			". Nothing was posted to Discord; this is the maintainer's decision on a PR of ours, for you to act on or not."
		for marked, earlier := range map[string]any{"no mark": nil, "a reopened seat's mark": run.Fields("line", line, "seat", 900)} {
			t.Run(decided+", "+marked, func(t *testing.T) {
				ak, home := forkSeat(t)
				dir := filepath.Join(ak, "runs", "20261107-0900-add-retry-file")
				record := run.Fields("state", "pass", "title", "Add retry file", "foreign", true, "pr", address,
					"launched_session", "lead", "merge_note", "waiting for the maintainer")
				if earlier != nil {
					record.Set("decision_typed", earlier)
				}
				put(t, filepath.Join(dir, "run.json"), run.Line(record))
				put(t, filepath.Join(dir, "result.md"), "# NOT MERGED (1 of 3) — Add retry file\n")
				put(t, filepath.Join(home, "view"), view)
				put(t, filepath.Join(home, "jam"), filepath.Join(dir, "delivery.lock"))
				state, _ := loadState()
				tick := func() error {
					return (&ticking{state: state, log: newLog(io.Discard, io.Discard), clock: time.Now}).outgoing("beta")
				}
				if err := tick(); err == nil || errors.Is(err, errLeft) {
					t.Fatalf("a mark that could not be written ended the pass %v, not failing it", err)
				}
				// the ticks after take the lock
				for _, jam := range []string{filepath.Join(home, "jam"), filepath.Join(dir, "delivery.lock")} {
					if err := os.Remove(jam); err != nil {
						t.Fatal(err)
					}
				}
				for range 2 {
					if err := tick(); err != nil {
						t.Fatalf("the line waiting in the composer ended the pass %v", err)
					}
				}
				if typed := read(t, filepath.Join(home, "keys")); typed != line+"\n" {
					t.Fatalf("typed %q, not one copy of the line and no Enter", typed)
				}
			})
		}
	}
}
