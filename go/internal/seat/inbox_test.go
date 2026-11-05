package seat

import (
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestAMergeQuestionWaitsBehindAnOwnersQuestionButNotBehindAnEarlierMergeQuestion(t *testing.T) {
	home := sandbox(t)
	t.Setenv("AGENTKIT_INBOX_SESSION", "acme")
	record(t, home, "acme", nil)
	bin := filepath.Join(home, "bin")
	write(t, filepath.Join(bin, "tmux"), `#!/bin/sh
case "$*" in
  *list-sessions*) printf 'acme\t1\n' ;;
  *list-panes*) echo '%1 0' ;;
  *capture-pane*) cat "$HOME/shown" ;;
  *display-message*'#{pane_id}'*) printf '%%1\t1000\n' ;;
  *send-keys*)
    for last do :; done
    printf '%s\n' "$last" >> "$HOME/keys"
    if [ "$last" = Enter ]; then cp "$HOME/prompt" "$HOME/shown"
    else printf '────────\n❯ %s\n────────\n' "$last" > "$HOME/shown"; fi ;;
esac
`)
	if err := os.Chmod(filepath.Join(bin, "tmux"), 0o700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", bin+string(os.PathListSeparator)+os.Getenv("PATH"))
	write(t, filepath.Join(home, "prompt"), prompting)
	write(t, filepath.Join(home, "shown"), prompting)
	notice := filepath.Join(home, ".agentkit", "state", "notify-acme.json")
	sha := "0123456789abcdef0123456789abcdef01234567"
	ask := func() (sent, carried, typed bool) {
		sent, carried = AskInbox("PR #7 by beta: Fix api. Merge? yes/no", "https://github.com/acme/widgets/pull/7", sha,
			false, func() { typed = true }, func(string) {}, io.Discard)
		return sent, carried, typed
	}
	write(t, notice, `{"session": "acme", "kind": "needs", "text": "Deploy now?", "time": 1800000000, "source": null}`)
	if sent, carried, typed := ask(); sent || !carried || typed {
		t.Fatalf("asked past the owner's question: sent=%v carried=%v typed=%v", sent, carried, typed)
	}
	if keys, _ := os.ReadFile(filepath.Join(home, "keys")); len(keys) > 0 {
		t.Fatalf("typed behind the owner's question: %q", keys)
	}
	write(t, notice, `{"session": "acme", "kind": "needs", "text": "PR #6 by beta: Fix ui. Merge? yes/no", "time": 1800000000, "source": "inbox:https://github.com/acme/widgets/pull/6:abc"}`)
	if _, carried, typed := ask(); !carried || !typed {
		t.Fatal("an earlier merge question held this one back")
	}
	if keys, _ := os.ReadFile(filepath.Join(home, "keys")); !strings.Contains(string(keys), "--match-head-commit "+sha+"`") {
		t.Fatalf("the merge is not pinned to the commit reviewed: %q", keys)
	}
}
