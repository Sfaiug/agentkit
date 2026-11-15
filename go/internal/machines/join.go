package machines

import (
	"cmp"
	"context"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"agentkit/internal/commandhelp"
	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/lock"
)

// JoinLine is the line that makes a new Linux machine one ak reaches by its key, over Tailscale
// (Python's machines.join_line): tools/join.sh as this install's origin has it on its default
// branch, so a fork's is its own, or on GitHub's name for that branch where the clone has none.
func JoinLine() (string, error) {
	git := gitcall.Git{Repo: config.Repo()}
	origin, err := git.Try("remote", "get-url", "origin")
	if err != nil {
		return "", err
	}
	branch, err := git.Try("symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD")
	if err != nil {
		return "", err
	}
	public, err := publicKey()
	if err != nil {
		return "", err
	}
	url := "https://raw.githubusercontent.com/" + gitcall.OwnerName(origin) + "/" +
		cmp.Or(strings.TrimPrefix(branch, "origin/"), "HEAD") + "/tools/join.sh"
	return "curl -fsSL " + commandhelp.ShellJoin([]string{url}) + " | sudo bash -s -- " +
		commandhelp.ShellJoin([]string{public}) + " tailscale", nil
}

// publicKey is the public half of ak's key (route), the pair made the first time it is asked
// for, its private half its owner's alone.
func publicKey() (string, error) {
	if err := config.EnsureDirs(); err != nil {
		return "", err
	}
	// two screens asking at once make one pair, under Python's lock of it
	held, err := lock.Wait(context.Background(), filepath.Join(filepath.Dir(key()), ".machines-ssh.lock"))
	if err != nil {
		return "", err
	}
	defer held.Close()
	if _, err := os.Stat(key()); err != nil {
		if err := exec.Command("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "ak", "-f", key()).Run(); err != nil {
			return "", err
		}
	}
	public, err := os.ReadFile(key() + ".pub")
	return gitcall.Strip(string(public)), err
}

// key is ak's key pair to the machines it adds, Python's machines.KEY.
func key() string { return filepath.Join(config.Home(), "secrets", "machines-ssh") }
