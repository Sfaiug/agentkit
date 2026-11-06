package helper

import (
	"archive/tar"
	"bytes"
	"io"
	"maps"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"slices"
	"strings"
	"testing"

	"agentkit/internal/config"
)

// A turn on a worktree with an edited, a deleted, a new and an excluded file, lent a login and
// resuming a conversation, packs what Python's machine_turn._parcel packs there beside a suite's
// own: each name and its bytes as Python 3.11 packed them for this worktree, and a link as a link.
func TestATurnsParcelHoldsWhatPythonsHolds(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("the adapter and the harness program are shell scripts")
	}
	root := t.TempDir()
	home, adapters, tools, ours := filepath.Join(root, "home"), filepath.Join(root, "adapters"), filepath.Join(root, "tools"), filepath.Join(root, "ak")
	repo, work, out := filepath.Join(root, "repo"), filepath.Join(root, "wt", "fix-api"), filepath.Join(root, "out")
	const id = "0b5e8c1e-acme-4c3f"
	conversation := filepath.Join(home, ".gamma", "sessions", "proj")
	for path, content := range map[string]string{
		filepath.Join(home, ".agentkit", "config.toml"): "[models.acme]\nharness='gamma'\nmodel='acme-1'\neffort='low'\nprovider='acme'\n[providers.acme]\nmode='subscription'\n",
		filepath.Join(adapters, "gamma.toml"): "[update]\nversion = ['gamma-cli', '--version']\nupgrade = ['gamma-cli', 'upgrade']\n" +
			"[worker]\nsessions = ['~/.gamma/sessions/*/{id}*']\nlent_for = 600\n" +
			"[fetch]\naarch64 = 'https://gamma.example/{version}/arm64/gamma-cli'\nx86_64 = 'https://gamma.example/{version}/x64/gamma-cli'\n",
		filepath.Join(adapters, "gamma.sh"): "#!/bin/sh\n[ \"$1\" = lend ] || exit 2\nmkdir -p \"$2/.gamma\" &&\n" +
			"  printf '{\"token\":\"lent to %s\"}' \"$AGENTKIT_PROVIDER\" >\"$2/.gamma/login.json\" &&\n  echo $(( $(date +%s) + 3600 ))\n",
		filepath.Join(tools, "gamma-cli"):                                        "#!/bin/sh\necho 'gamma-cli 1.4.2 (build 7)'\n",
		filepath.Join(ours, "adapters", "gamma.sh"):                              "echo gamma\n",
		filepath.Join(ours, "agentkit", "run.py"):                                "print(\"run\")\n",
		filepath.Join(ours, "agentkit", "__pycache__", "run.pyc"):                "compiled\n",
		filepath.Join(ours, "bin", "ak"):                                         "#!/bin/sh\n",
		filepath.Join(repo, "kept.txt"):                                          "kept\n",
		filepath.Join(repo, "edited.txt"):                                        "before\n",
		filepath.Join(repo, "gone.txt"):                                          "doomed\n",
		filepath.Join(out, "prompt.md"):                                          "the task\n",
		filepath.Join(out, "notes", "one.md"):                                    "noted\n",
		filepath.Join(conversation, id+".jsonl"):                                 "{\"said\":\"hi\"}\n",
		filepath.Join(conversation, id, "agent.jsonl"):                           "{\"sub\":1}\n",
		filepath.Join(home, ".gamma", "sessions", "other", "someone-else.jsonl"): "{\"not\":\"this\"}\n",
	} {
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			t.Fatal(err)
		}
		// executable, as the scripts among them must be
		if err := os.WriteFile(path, []byte(content), 0o755); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.Mkdir(filepath.Join(ours, "tools"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink("../bin/ak", filepath.Join(ours, "tools", "shim")); err != nil {
		t.Fatal(err)
	}
	for key, value := range map[string]string{"HOME": home, "USERPROFILE": home, "AGENTKIT_ADAPTER_DIR": adapters,
		"GIT_CONFIG_NOSYSTEM": "1", "PATH": tools + string(os.PathListSeparator) + os.Getenv("PATH")} {
		t.Setenv(key, value)
	}
	shipped := checkout
	checkout = func() string { return ours }
	t.Cleanup(func() { checkout = shipped })
	git := func(args ...string) string {
		said, err := exec.Command("git", args...).Output()
		if err != nil {
			t.Fatalf("git %v: %v", args, err)
		}
		return string(said)
	}
	git("init", "-q", "-b", "main", repo)
	git("-C", repo, "config", "user.name", "Ada Lovelace")
	git("-C", repo, "config", "user.email", "ada@example.com")
	git("-C", repo, "add", "-A")
	git("-C", repo, "commit", "-q", "-m", "first")
	git("-C", repo, "worktree", "add", "-q", "-b", "fix-api", work)
	for path, content := range map[string]string{filepath.Join(work, "edited.txt"): "after\n", filepath.Join(work, "new.txt"): "fresh\n",
		filepath.Join(work, "secret.txt"): "private\n", filepath.Join(repo, ".git", "info", "exclude"): "secret.txt\n"} {
		if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	if err := os.Remove(filepath.Join(work, "gone.txt")); err != nil {
		t.Fatal(err)
	}
	marker := filepath.Join(root, "runs", "fix-api")
	env := map[string]string{"AGENTKIT_RUN": marker, "AK_ROUND": "2", "BASH_ENV": "/etc/ak-bash", "HOME": home,
		"LANG": "C.UTF-8", "PATH": "/usr/bin:/bin", "SECRET": "kept here", "SHELL": "/bin/bash"}

	files, err := turnFiles(config.Model{Harness: "gamma", Provider: "acme"}, filepath.Join(adapters, "gamma.sh"), work, out, env, id)
	if err != nil || files == nil {
		t.Fatalf("the turn packs nothing: %v", err)
	}
	var parcel bytes.Buffer
	if err := (&Away{}).pack(work, nil, files, &parcel); err != nil {
		t.Fatal(err)
	}
	have, links := map[string]string{}, map[string]string{}
	for in := tar.NewReader(&parcel); ; {
		head, err := in.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			t.Fatal(err)
		}
		data, err := io.ReadAll(in)
		if err != nil {
			t.Fatal(err)
		}
		have[head.Name], links[head.Name] = string(data), head.Linkname
	}

	turn, err := os.ReadFile(filepath.Join("..", "..", "..", "tools", "helper", "turn.sh"))
	if err != nil {
		t.Fatal(err)
	}
	piece, _ := carried.ReadFile("piece.sh")
	want := map[string]string{
		"piece.sh": string(piece), "heads": git("-C", work, "rev-parse", "HEAD"), "repo.bundle": have["repo.bundle"],
		"turn.sh": string(turn),
		"out/":    "", "out/notes/": "", "out/notes/one.md": "noted\n", "out/prompt.md": "the task\n",
		"ak/adapters/": "", "ak/adapters/gamma.sh": "echo gamma\n", "ak/agentkit/": "", "ak/agentkit/run.py": "print(\"run\")\n",
		"ak/bin/": "", "ak/bin/ak": "#!/bin/sh\n", "ak/tools/": "", "ak/tools/shim": "",
		"paths":            "edited.txt\x00gone.txt\x00new.txt\x00",
		"dirty/edited.txt": "after\n", "dirty/new.txt": "fresh\n",
		"exclude":                "secret.txt\n",
		"home/.gitconfig":        "[user]\n\tname = Ada Lovelace\n\temail = ada@example.com\n",
		"lent":                   ".gamma/login.json\x00",
		"home/.gamma/login.json": "{\"token\":\"lent to acme\"}",
		"home/.gamma/sessions/proj/" + id + ".jsonl":       "{\"said\":\"hi\"}\n",
		"home/.gamma/sessions/proj/" + id + "/":            "",
		"home/.gamma/sessions/proj/" + id + "/agent.jsonl": "{\"sub\":1}\n",
		"harness":       "gamma/1.4.2/gamma-cli",
		"fetch/aarch64": "https://gamma.example/1.4.2/arm64/gamma-cli",
		"fetch/x86_64":  "https://gamma.example/1.4.2/x64/gamma-cli",
		"env": "AGENTKIT_RUN=" + marker + "\x00AK_ROUND=2\x00BASH_ENV=/etc/ak-bash\x00HOME=" + home +
			"\x00LANG=C.UTF-8\x00SHELL=/bin/bash\x00TMPDIR=/var/tmp\x00",
	}
	if names, wanted := slices.Sorted(maps.Keys(have)), slices.Sorted(maps.Keys(want)); !slices.Equal(names, wanted) {
		t.Errorf("the parcel holds\n%s\nnot Python's\n%s", strings.Join(names, "\n"), strings.Join(wanted, "\n"))
	}
	for name, data := range want {
		if have[name] != data {
			t.Errorf("%s holds %q, not Python's %q", name, have[name], data)
		}
	}
	if links["ak/tools/shim"] != "../bin/ak" {
		t.Errorf("ak/tools/shim links to %q, not ../bin/ak", links["ak/tools/shim"])
	}
}
