//go:build unix

package worker

import (
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// aMachineTakesTurns is a checkout under root, repo, whose model glint's turns go to the machine
// acme, its ssh what put writes at bin/ssh; a turn of glint run here runs gamma.sh's `run` as run
// says, its out dir $6.
func aMachineTakesTurns(t *testing.T, run string) (root, repo string, put func(at, text string), git func(args ...string) string) {
	root = t.TempDir()
	home, bin, adapters := filepath.Join(root, "home"), filepath.Join(root, "bin"), filepath.Join(root, "adapters")
	repo = filepath.Join(root, "repo")
	for key, value := range map[string]string{"HOME": home, "USERPROFILE": home, "AGENTKIT_ADAPTER_DIR": adapters, "GIT_CONFIG_NOSYSTEM": "1",
		"GIT_AUTHOR_NAME": "a", "GIT_AUTHOR_EMAIL": "a@example.com", "GIT_COMMITTER_NAME": "a", "GIT_COMMITTER_EMAIL": "a@example.com",
		"AGENTKIT_RUN": "", "AGENTKIT_RUN_DIR": "", "AGENTKIT_SESSION": "", "PATH": bin + string(os.PathListSeparator) + os.Getenv("PATH")} {
		t.Setenv(key, value)
	}
	for _, key := range []string{"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"} {
		t.Setenv(key, "")
		os.Unsetenv(key)
	}
	put = func(at, text string) {
		t.Helper()
		// executable, as the scripts among them must be
		if os.MkdirAll(filepath.Dir(at), 0o755) != nil || os.WriteFile(at, []byte(text), 0o755) != nil {
			t.Fatalf("cannot write %s", at)
		}
	}
	git = func(args ...string) string {
		t.Helper()
		said, err := exec.Command("git", append([]string{"-C", repo}, args...)...).CombinedOutput()
		if err != nil {
			t.Fatalf("git %s: %v\n%s", strings.Join(args, " "), err, said)
		}
		return strings.TrimSpace(string(said))
	}
	put(filepath.Join(home, ".agentkit", "config.toml"), "[models.glint]\nharness='gamma'\nmodel='gamma-1'\neffort='high'\nprovider='acme'\n"+
		"[providers.acme]\nmode='subscription'\n[machines.acme]\nwork=['turns']\n")
	// the adapters' folder is the harness's state, so a turn's box here sees gamma.sh
	put(filepath.Join(adapters, "gamma.toml"), "version=1\n[worker]\nstate=['"+filepath.ToSlash(adapters)+"']\nsessions=['~/.gamma/{id}.jsonl']\nlent_for=300\n"+
		"[fetch]\naarch64='https://gamma.example/{version}/gamma'\nx86_64='https://gamma.example/{version}/gamma'\n"+
		"[update]\nversion=['gamma','--version']\nupgrade=['gamma','upgrade']\n")
	put(filepath.Join(bin, "gamma"), "#!/bin/sh\necho 'gamma 1.2.3'\n")
	put(filepath.Join(adapters, "gamma.sh"), "#!/bin/sh\ncase \"$1\" in\nauth) echo ready ;;\n"+
		"lend) mkdir -p \"$2/.gamma\" && echo lent >\"$2/.gamma/login\" && echo $(( $(date +%s) + 86400 )) ;;\n"+
		"run) "+run+" ;;\nesac\n")
	put(filepath.Join(repo, "tools", "helper", "Containerfile"), "FROM scratch\n")
	git("init", "-q", "-b", "main")
	git("add", "-A")
	git("commit", "-q", "-m", "base")
	return root, repo, put, git
}

// A turn a machine ran to its end is no silent turn however long its results take to come home
// and the machine to let it go: the worker's watch covers the turn alone, as Python's watch does
// the ssh alone, before machine_turn._home.
func TestATurnsHomecomingIsNoSilence(t *testing.T) {
	// a turn run here would leave the conversation "local"
	root, repo, put, git := aMachineTakesTurns(t, `echo local >"$6/session_id"`)
	home, result := filepath.Join(root, "home"), filepath.Join(root, "result")
	base := git("rev-parse", "HEAD")
	// what the machine sends back: the commit of what the turn left, its exit, its out dir and
	// the conversation it reported
	git("commit", "-q", "--allow-empty", "-m", "left")
	git("update-ref", "refs/ak/left", "HEAD")
	put(filepath.Join(result, "code"), "0\n")
	git("bundle", "create", "-q", filepath.Join(result, "back.bundle"), "refs/ak/left", "^"+base)
	git("reset", "-q", "--hard", base)
	git("update-ref", "-d", "refs/ak/left")
	put(filepath.Join(result, "out", "session_id"), "received\n")
	put(filepath.Join(result, "home", ".gamma", "received.jsonl"), "whole\n")
	// The turn there ends at once; collecting its results and letting it go each take longer
	// than the turn's silence limit.
	put(filepath.Join(root, "bin", "ssh"), "#!/bin/sh\neval \"set -- $8\"\ncase \"$5\" in\n"+
		"probe) printf 'cpus 2\\nload 0\\nroom_mb 65536\\nturns 1\\n' ;;\nprepare) cat >/dev/null ;;\n"+
		"turn) echo '{\"session_id\":\"received\"}' ;;\n"+
		"collect) sleep 3; tar -C '"+result+"' -cf - code back.bundle out home ;;\nfinish) sleep 3 ;;\nesac\n")
	code, session, err := Turn("glint", "reviewer", "review it", repo, filepath.Join(root, "out"), "", Given{Silence: time.Second}, io.Discard)
	if code != 0 || session != "received" || err != nil {
		t.Fatalf("the turn the machine ended: exit %d, conversation %q, %v", code, session, err)
	}
	if _, err := os.Stat(filepath.Join(home, ".gamma", "received.jsonl")); err != nil {
		t.Errorf("its conversation did not come home: %v", err)
	}
}
