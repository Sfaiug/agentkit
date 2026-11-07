//go:build linux

package box

import (
	"context"
	"os"
	"path/filepath"
	"testing"

	"agentkit/internal/host"
)

func TestACheckIsNamedTheAccountsGoCacheOnlyWhereItsHomesOverlayAloneShowsIt(t *testing.T) {
	if err := Check(); err != nil {
		t.Skip(err)
	}
	for _, check := range []struct {
		why, cache, out string
		env             map[string]string
		named           bool
	}{
		{why: "the account's", cache: ".cache/go-build", named: true},
		{why: "none missing"},
		{why: "none holding a writable place", cache: ".cache/go-build", out: ".cache/go-build/ab"},
		{why: "none hidden", cache: ".ssh/go-build", env: map[string]string{"XDG_CACHE_HOME": ".ssh"}},
		{why: "none where the command names its own, even empty", cache: ".cache/go-build", env: map[string]string{"GOCACHE": ""}},
	} {
		home, err := filepath.EvalSymlinks(t.TempDir())
		if err != nil {
			t.Fatal(err)
		}
		env := map[string]string{"HOME": home, "PATH": os.Getenv("PATH"), "GOTOOLCHAIN": "local"}
		for key, value := range check.env {
			if value != "" {
				value = filepath.Join(home, value) // a place a case names is in its home
			}
			env[key] = value
		}
		out := filepath.Join(home, check.out)
		if check.out == "" {
			out = t.TempDir()
		}
		for _, made := range []string{filepath.Join(home, check.cache), out} {
			if err := os.MkdirAll(made, 0o777); err != nil {
				t.Fatal(err)
			}
		}
		said, err := os.Create(filepath.Join(t.TempDir(), "output"))
		if err != nil {
			t.Fatal(err)
		}
		code, _, err := RunCheck(context.Background(), host.Watch{}, []string{"sh", "-c", `printf %s "${GOCACHE-}"`}, env, t.TempDir(), out, said)
		named, _ := os.ReadFile(said.Name())
		said.Close()
		want := ""
		if check.named {
			want = filepath.Join(home, check.cache)
		}
		if err != nil || code != 0 || string(named) != want {
			t.Errorf("%s: exit %d, %v, named %q, not %q", check.why, code, err, named, want)
		}
	}
}
