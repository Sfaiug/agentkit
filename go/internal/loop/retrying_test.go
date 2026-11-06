//go:build linux

package loop

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/config/adapters"
	"agentkit/internal/handin"
	"agentkit/internal/run"
	"agentkit/internal/worker"
)

// adapterRig is a loop whose model `opus` runs a script: each turn runs the case of its number, `$n`,
// its out directory `$out` and the session it was told `$session`.
func adapterRig(t *testing.T, silence time.Duration, turns string) (*loop, *call) {
	t.Helper()
	l := rig(t, silence)
	adapters := filepath.Join(t.TempDir(), "adapters")
	if err := os.MkdirAll(adapters, 0o777); err != nil {
		t.Fatal(err)
	}
	t.Setenv("AGENTKIT_ADAPTER_DIR", adapters)
	script := `#!/bin/bash
[ "$1" = run ] || { echo fine; exit 0; }
dir=` + adapters + `
out=$6 session=$7
n=$(( $(cat "$dir/n" 2>/dev/null || echo 0) + 1 )); echo $n > "$dir/n"
echo "$session" >> "$dir/sessions"
echo "${session:-sid-$n}" > "$out/session_id"
: > "$out/stderr.log"; : > "$out/final.md"
case $n in
` + turns + `
esac
`
	if err := os.WriteFile(filepath.Join(adapters, "acme.sh"), []byte(script), 0o755); err != nil {
		t.Fatal(err)
	}
	manifest := fmt.Sprintf("version = 1\n\n[worker]\nstate = [%q]\n\n[stall]\nrefusals = [\"500\"]\nquotas = [\"usage limit\"]\n", adapters)
	if err := os.WriteFile(filepath.Join(adapters, "acme.toml"), []byte(manifest), 0o666); err != nil {
		t.Fatal(err)
	}
	settings := "[defaults]\norchestrator = \"opus\"\nworkers = [\"opus\"]\n\n[audit]\non = false\n\n[models.opus]\nharness = \"acme\"\nmodel = \"opus\"\neffort = \"high\"\nprovider = \"acme\"\n\n[providers.acme]\nmode = \"subscription\"\n"
	if err := os.WriteFile(filepath.Join(config.Home(), "config.toml"), []byte(settings), 0o666); err != nil {
		t.Fatal(err)
	}
	backoff := transientBackoff
	transientBackoff = []time.Duration{time.Millisecond, time.Millisecond}
	t.Cleanup(func() { transientBackoff = backoff })
	model, err := config.ModelNamed("opus")
	if err != nil {
		t.Fatal(err)
	}
	return l, &call{l: l, name: "opus", role: "executor", model: model, body: "the task", out: filepath.Join(l.roundDir(), "executor")}
}

func (l *loop) logged(t *testing.T) string {
	t.Helper()
	data, _ := os.ReadFile(filepath.Join(l.dir, "log.txt"))
	return string(data)
}

func TestAnEmptyExitGoesAgainOnItsSessionWithTheRecordSayingUntilWhen(t *testing.T) {
	l, c := adapterRig(t, time.Minute, `1) exit 1;;
2) echo "## Summary" > "$out/final.md";;`)
	done, err := c.run()
	if err != nil {
		t.Fatal(err)
	}
	if filepath.Base(done.out) != "executor-retry1" || c.session != "sid-1" {
		t.Fatalf("answered in %s on %s", done.out, c.session)
	}
	if want := "WARN executor opus exited 1 with an empty final.md (attempt 1); retrying in 0s, resuming session sid-1"; !strings.Contains(l.logged(t), want) {
		t.Fatal(l.logged(t))
	}
	record, _ := run.Read(l.dir)
	if wait := record.Dict("transient_wait"); wait == nil || !wait.Has("until") || !wait.Has("pid") {
		t.Fatalf("record %s", run.Line(record))
	}
}

func TestASilentTurnIsStoppedAndGoesAgain(t *testing.T) {
	l, c := adapterRig(t, 2*time.Second, `1) sleep 60;;
2) echo "## Summary" > "$out/final.md";;`)
	done, err := c.run()
	if err != nil {
		t.Fatal(err)
	}
	want := "WARN executor opus emitted no event for 2s and was killed with everything it spawned (session sid-1) (attempt 1)"
	if filepath.Base(done.out) != "executor-retry1" || !strings.Contains(l.logged(t), want) {
		t.Fatalf("answered in %s: %s", done.out, l.logged(t))
	}
}

func TestASignalResumesOnceThenAPersonLooks(t *testing.T) {
	l, c := adapterRig(t, time.Minute, `*) kill -TERM $$;;`)
	_, err := c.run()
	var killed *killedTwice
	if !errors.As(err, &killed) || !strings.HasPrefix(killed.why, "executor opus killed (SIGTERM) twice within a minute; see ") {
		t.Fatalf("ended %v", err)
	}
	if !strings.Contains(l.logged(t), "WARN executor opus killed (SIGTERM); resuming once, resuming session sid-1") {
		t.Fatal(l.logged(t))
	}
}

func TestANeverRunHarnessOutranksTheRefusalWords(t *testing.T) {
	_, c := adapterRig(t, time.Minute, `*) echo "acme: unknown model 500" > "$out/stderr.log"; exit 1;;`)
	_, err := c.run()
	var broken *cannotRun
	var cannot *blocked
	if !errors.As(err, &broken) || broken.line != "acme: unknown model 500" || !errors.As(err, &cannot) || cannot.why != "opus cannot run: acme: unknown model 500" {
		t.Fatalf("ended %v", err)
	}
}

func TestASpentWindowParksTheProviderAndGoesNoFurtherHere(t *testing.T) {
	l, c := adapterRig(t, time.Minute, `*) echo "You hit your usage limit." > "$out/final.md"; exit 1;;`)
	_, err := c.run()
	var refused *ranDry
	if !errors.As(err, &refused) || refused.message != "You hit your usage limit." {
		t.Fatalf("ended %v", err)
	}
	if !strings.Contains(l.logged(t), "WARN executor opus refused: You hit your usage limit.; nothing is picked on acme until ") {
		t.Fatal(l.logged(t))
	}
}

// A clean exit is heard only through the record kind `[stall] terminal` names, a string.
func TestACleanExitsTerminalRefusalParksTheProvider(t *testing.T) {
	_, c := adapterRig(t, time.Minute, `*) echo '{"type":"result","is_error":true,"result":"You hit your usage limit."}' > "$out/events.jsonl";;`)
	manifest := filepath.Join(os.Getenv("AGENTKIT_ADAPTER_DIR"), "acme.toml")
	data, _ := os.ReadFile(manifest)
	if err := os.WriteFile(manifest, append(data, "terminal = \"result\"\n"...), 0o666); err != nil {
		t.Fatal(err)
	}
	_, err := c.run()
	var refused *ranDry
	if !errors.As(err, &refused) || refused.message != "You hit your usage limit." {
		t.Fatalf("ended %v", err)
	}
}

func TestARefusedReviewKeepsWhatItsVerdictAskHandedIn(t *testing.T) {
	l, _ := adapterRig(t, time.Minute, `1) echo "## Partial" > "$out/final.md";;
*) echo '{"kind":"finding","path":"a.txt","line":1,"what":"w","why":"y","evidence":{"run":"false","returncode":1,"output":""}}' >> "$AK_HAND_IN"
   echo "You hit your usage limit." > "$out/final.md"; exit 1;;`)
	l.executor, l.reviewer = "opus", "opus"
	if err := os.WriteFile(filepath.Join(l.workspace, "a.txt"), []byte("a\n"), 0o666); err != nil {
		t.Fatal(err)
	}
	if _, err := l.review("work", true, "$ true\n[exit 0]", ""); err == nil {
		t.Fatal("the review went on with nobody to give it")
	}
	record, _ := run.Read(l.dir)
	if filepath.Base(filepath.Dir(record.Str("findings_file"))) != "reviewer-attempt2" || len(record.List("review_records")) != 1 {
		t.Fatalf("record %s", run.Line(record))
	}
}

func TestARefusalsOwnReportDatesTheProvidersPark(t *testing.T) {
	until := time.Now().Unix() + 7200
	_, c := adapterRig(t, time.Minute, fmt.Sprintf(`*) echo '{"meters":[{"name":"window","used":100,"resets_at":%d,"window_secs":18000}]}' > "$out/%s"
   echo "You hit your usage limit." > "$out/final.md"; exit 1;;`, until, adapters.RefusalReport))
	dir := os.Getenv("AGENTKIT_ADAPTER_DIR")
	for _, kind := range []string{".sh", ".toml"} {
		if err := os.Rename(filepath.Join(dir, "acme"+kind), filepath.Join(dir, "muse"+kind)); err != nil {
			t.Fatal(err)
		}
	}
	settings := filepath.Join(config.Home(), "config.toml")
	held, err := os.ReadFile(settings)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(settings, []byte(strings.ReplaceAll(strings.ReplaceAll(string(held), `"acme"`, `"muse"`), "providers.acme", "providers.muse")), 0o666); err != nil {
		t.Fatal(err)
	}
	if c.model, err = config.ModelNamed("opus"); err != nil {
		t.Fatal(err)
	}
	var refused *ranDry
	if _, err := c.run(); !errors.As(err, &refused) {
		t.Fatalf("ended %v", err)
	}
	saved, err := run.ReadJSON(filepath.Join(config.Home(), "state", "usage.json"))
	if err != nil {
		t.Fatal(err)
	}
	if at, _ := saved.Dict("providers").Dict("muse").Num("exhausted_until"); at != float64(until) {
		t.Fatalf("parked until %v, the report says %d", at, until)
	}
}

func TestTheSecondFlakeInARowTriesTheNextWorkerOnce(t *testing.T) {
	_, c := adapterRig(t, time.Minute, `*) echo 'API Error: 500' > "$out/final.md"; exit 1;;`)
	var offered []string
	c.handover = func(detail string) (string, error) {
		offered = append(offered, detail)
		return "astra", nil
	}
	_, err := c.run()
	var handed *handedOver
	if !errors.As(err, &handed) || handed.next != "astra" || len(offered) != 1 || offered[0] != "transient '500': API Error: 500 (twice in a row)" {
		t.Fatalf("ended %v, offered %q", err, offered)
	}
}

func TestAFlakeNobodyCanTakeWaitsOnAndTheRetryInheritsItsRecords(t *testing.T) {
	l, c := adapterRig(t, time.Minute, `1|2) exit 1;;
3) echo "## Summary" > "$out/final.md";;`)
	c.handover = func(string) (string, error) { return "", nil }
	done, err := c.run()
	if err != nil {
		t.Fatal(err)
	}
	if filepath.Base(done.out) != "executor-retry2" || !strings.Contains(l.logged(t), "(twice in a row); no other worker can take it") {
		t.Fatalf("answered in %s: %s", done.out, l.logged(t))
	}
	if _, found := handin.Read(filepath.Join(done.out, handin.File)); !found {
		t.Fatal("no record file")
	}
}

func TestAResumeThatNeverOpensGoesOnInANewConversation(t *testing.T) {
	l, c := adapterRig(t, time.Minute, `1) exit 1;;
2) echo "## Summary" > "$out/final.md";;`)
	c.session, c.fresh = "gone", "the whole task"
	done, err := c.run()
	if err != nil {
		t.Fatal(err)
	}
	told, _ := os.ReadFile(filepath.Join(done.out, "prompt.md"))
	if c.session != "sid-2" || !strings.Contains(string(told), "the whole task") || !strings.Contains(l.logged(t), "resume of gone failed; fresh conversation") {
		t.Fatalf("session %q told %q: %s", c.session, told, l.logged(t))
	}
}

func TestABackgroundReportDoesNotGetAnotherTurn(t *testing.T) {
	for _, role := range []string{"executor", "fixer", "reviewer"} {
		t.Run(role, func(t *testing.T) {
			_, c := adapterRig(t, time.Minute, `*) echo "Background tasks still running" > "$out/stderr.log"
   echo '{"type":"background_tasks_changed","tasks":[{}]}' > "$out/events.jsonl"
   echo "## Summary" > "$out/final.md";;`)
			c.role, c.out = role, filepath.Join(c.l.roundDir(), role)
			done, err := c.run()
			if err != nil {
				t.Fatal(err)
			}
			if done.out != c.out || done.text != "## Summary\n" || c.calls != 1 {
				t.Fatalf("answered in %s after %d calls: %q", done.out, c.calls, done.text)
			}
		})
	}
}

func TestALoginThatExpiredTravelsUpWithoutAWait(t *testing.T) {
	l, c := adapterRig(t, time.Minute, `*) ;;`)
	adapter, _ := config.Adapter("acme")
	script, _ := os.ReadFile(adapter)
	refusing := strings.Replace(string(script), `[ "$1" = run ] || { echo fine; exit 0; }`, `[ "$1" = auth ] && { echo logged out; exit 1; }`, 1)
	if err := os.WriteFile(adapter, []byte(refusing), 0o755); err != nil {
		t.Fatal(err)
	}
	_, err := c.run()
	var login *worker.LoginExpired
	if !errors.As(err, &login) || login.Why != "logged out" {
		t.Fatalf("ended %v", err)
	}
	if !strings.Contains(l.logged(t), "executor opus cannot authenticate: logged out; the run waits for that login rather than retrying into it") {
		t.Fatal(l.logged(t))
	}
}

func TestParkedEndingsWriteTheirRecordsAsPythonDoes(t *testing.T) {
	for _, each := range []struct {
		err   error
		said  string
		state string
	}{
		{&worker.LoginExpired{Harness: "acme", Why: "logged out"}, "waiting for login: acme login expired: logged out", "waiting_login"},
		{&killedTwice{"killed twice"}, "killed: killed twice", "interrupted"},
		{&exhausted{"spent", true}, "exhausted: spent", "exhausted"},
	} {
		said, park, stands := parked(each.err)
		if !stands || said != each.said {
			t.Fatalf("%v: %q", each.err, said)
		}
		record := run.Fields("error_retries", 1, "waiting_for", "other")
		park(record)
		if record.Str("state") != each.state {
			t.Fatalf("%v: %s", each.err, run.Line(record))
		}
	}
	record := run.Fields("error_retries", 1, "waiting_for", "other")
	_, park, _ := parked(&exhausted{"spent", true})
	park(record)
	if !record.Truthy("quota_dry") || record.Has("waiting_for") || record.Has("error_retries") {
		t.Fatalf("quota: %s", run.Line(record))
	}
}

func TestTheRoundsAHandoverCreditsStartWhereTheModelTookOver(t *testing.T) {
	record := run.NewObject()
	noteHandover(record, "opus", "astra", "transient", 2)
	noteHandover(record, "astra", "spark", "ran dry", 3)
	if got := run.Line(record.Get("executor_history")); !strings.Contains(got, `"rounds": [1, 2]`) || !strings.Contains(got, `"rounds": [2, 3]`) {
		t.Fatal(got)
	}
}
