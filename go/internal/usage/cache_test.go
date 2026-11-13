package usage

import (
	"os"
	"path/filepath"
	"slices"
	"testing"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

func TestAReadingOfALoginConfigNoLongerListsLeavesTheSnapshotAlone(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	if err := os.MkdirAll(state(), 0o700); err != nil {
		t.Fatal(err)
	}
	listed := "[models.anvil]\nharness='echo'\nmodel='anvil-1'\neffort='high'\nprovider='acme'\n" +
		"[providers.acme]\nmode='subscription'\naccounts=['default','two']\n"
	if err := os.WriteFile(filepath.Join(home, ".agentkit", "config.toml"), []byte(listed), 0o600); err != nil {
		t.Fatal(err)
	}
	now := clock()
	week := func(used float64) *run.Object {
		return fields("meters", []any{fields("name", "weekly", "used", used, "window_secs", 604800, "resets_at", now+86400)})
	}
	held := fields("acme", fields("accounts", fields("default", week(30), "two", week(70))))
	if err := os.WriteFile(filepath.Join(state(), "usage.json"), []byte(run.Line(fields("fetched_at", now, "providers", held))), 0o600); err != nil {
		t.Fatal(err)
	}
	acme := config.Subscription{Name: "acme"}
	for _, src := range []source{{Subscription: acme}, {Subscription: acme, account: "three"}} {
		patch(src, week(10))
		if got := object(read()).Get("providers"); run.Line(got) != run.Line(held) {
			t.Fatalf("login %q rewrote the snapshot: %s", src.account, run.Line(got))
		}
	}
}

func TestAReadWritesTheProvidersAndAccountsConfigListsAsItWrites(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	if err := os.MkdirAll(state(), 0o700); err != nil {
		t.Fatal(err)
	}
	// swapped while the read asked: acme's account three for two and four, its provider crate for
	// brine; only two has been read since
	listed := "[models.anvil]\nharness='echo'\nmodel='anvil-1'\neffort='high'\nprovider='acme'\n" +
		"[models.bale]\nharness='echo'\nmodel='bale-1'\neffort='high'\nprovider='brine'\n" +
		"[providers.acme]\nmode='subscription'\naccounts=['default','two','four']\n[providers.brine]\nmode='subscription'\n"
	if err := os.WriteFile(filepath.Join(home, ".agentkit", "config.toml"), []byte(listed), 0o600); err != nil {
		t.Fatal(err)
	}
	now := clock()
	week := func(used float64) *run.Object {
		return fields("meters", []any{fields("name", "weekly", "used", used, "window_secs", 604800, "resets_at", now+86400)})
	}
	held := fields("acme", fields("accounts", fields("default", week(30), "two", week(70))), "brine", week(20))
	if err := os.WriteFile(filepath.Join(state(), "usage.json"), []byte(run.Line(fields("fetched_at", now, "providers", held))), 0o600); err != nil {
		t.Fatal(err)
	}
	acme, crate := config.Subscription{Name: "acme"}, config.Subscription{Name: "crate"}
	sources := []source{{Subscription: acme, account: "default"}, {Subscription: acme, account: "three"}, {Subscription: crate}}
	mine := fields("acme", fields("accounts", fields("default", week(30), "three", week(90))), "crate", week(50))
	answer, err := store(sources, mine, nil, now, &now, nil)
	if err != nil {
		t.Fatal(err)
	}
	disk := object(object(read()).Get("providers"))
	accounts := disk.Dict("acme").Dict("accounts")
	if !slices.Equal(disk.Keys(), []string{"acme", "brine"}) || !slices.Equal(accounts.Keys(), []string{"default", "two"}) ||
		!slices.ContainsFunc(objects(accounts.Dict("two").Get("meters")), func(meter *run.Object) bool { return used(meter) == 70 }) {
		t.Fatalf("a read from before the swap rewrote the snapshot: %s", run.Line(disk))
	}
	if got := answer.Keys(); !slices.Equal(got, []string{"acme"}) {
		t.Fatalf("answered %v, not what it asked that config.toml still lists", got)
	}
}

// A snapshot that cannot be written is the read's error, read cold or answered from the cache,
// never a panic that ends the job checking its budget.
func TestAReadWhoseSnapshotCannotBeWrittenSaysWhy(t *testing.T) {
	for _, cached := range []bool{false, true} {
		home := t.TempDir()
		t.Setenv("HOME", home)
		t.Setenv("USERPROFILE", home)
		adapters := filepath.Join(home, "adapters")
		for _, dir := range []string{state(), adapters} {
			if err := os.MkdirAll(dir, 0o700); err != nil {
				t.Fatal(err)
			}
		}
		t.Setenv("AGENTKIT_ADAPTER_DIR", adapters)
		files := map[string]string{
			filepath.Join(home, ".agentkit", "config.toml"): "[models.anvil]\nharness='claude'\nmodel='anvil-1'\neffort='high'\nprovider='acme'\n" +
				"[providers.acme]\nmode='subscription'\n",
			filepath.Join(home, ".agentkit", "work"): "not a directory\n", // so no write can take its lock
			filepath.Join(adapters, "claude.sh"):     "#!/bin/sh\nprintf 'ready\\n'\n",
		}
		if cached { // fresh, but without the reset count a read writes down
			files[filepath.Join(state(), "usage.json")] = run.Line(fields("fetched_at", clock(), "providers",
				fields("acme", fields("harness", "claude", "none", true, "meters", []any{}, "accounts", run.NewObject()))))
		}
		for path, data := range files {
			if err := os.WriteFile(path, []byte(data), 0o700); err != nil {
				t.Fatal(err)
			}
		}
		if _, err := Read(); err == nil {
			t.Fatalf("cached=%v: a snapshot that cannot be written read as written", cached)
		}
	}
}
