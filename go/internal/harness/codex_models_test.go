package harness

import (
	"bytes"
	"os"
	"path/filepath"
	"runtime"
	"testing"
)

// codexListing is a HOME whose codex answers with the file `listing` there, exiting as the file
// `exit` says, else 0, and logs each call to `asked`: its words, then the login it ran on.
func codexListing(t *testing.T) (home string, write func(path, text string)) {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Skip("the fake codex is a shell script")
	}
	home = t.TempDir()
	write = func(path, text string) {
		path = filepath.Join(home, path)
		os.MkdirAll(filepath.Dir(path), 0o700)
		os.WriteFile(path, []byte(text), 0o700)
	}
	write("bin/codex", `#!/bin/sh
printf '%s\n' "$*" "${CODEX_HOME-unset} ${OPENAI_API_KEY-unset} ${CODEX_API_KEY-unset}" >> "$HOME/asked"
cat "$HOME/listing" 2>/dev/null
exit $(cat "$HOME/exit" 2>/dev/null || echo 0)
`)
	for key, value := range map[string]string{"HOME": home, "AGENTKIT_ADAPTER_DIR": "", "AGENTKIT_ACCOUNT": "",
		"OPENAI_API_KEY": "", "CODEX_API_KEY": "",
		"PATH": filepath.Join(home, "bin") + string(os.PathListSeparator) + os.Getenv("PATH")} {
		t.Setenv(key, value)
	}
	t.Setenv("CODEX_HOME", "")
	os.Unsetenv("CODEX_HOME")
	return home, write
}

// `models` answers as adapters/codex.sh does: the table's `default` first, then each model the
// listing marks `list`, its slug, display name and efforts, as jq's @tsv writes them; 1, saying
// nothing, where codex fails, its answer is no listing jq reads, or it lists nothing.
func TestCodexModelsListsAsItsScript(t *testing.T) {
	_, write := codexListing(t)
	write("listing", `{"models": [
  {"slug": "gpt-6-astra", "display_name": "GPT-6 Astra", "visibility": "list",
   "supported_reasoning_levels": [{"effort": "low", "description": "fast"}, {"effort": "high"}]},
  {"slug": "gpt-6-luna", "display_name": "GPT-6 Luna", "visibility": "hide",
   "supported_reasoning_levels": [{"effort": "low"}]},
  null,
  {"slug": "acme\tnova", "display_name": null, "visibility": "list", "supported_reasoning_levels": null}]}`)
	var out, errOut bytes.Buffer
	if code := Verb("codex", "models")(nil, &out, &errOut); code != 0 {
		t.Fatalf("exit %d: %q", code, errOut.String())
	}
	if want := "default\tCodex's own model\tlow medium high xhigh max ultra\n" +
		"gpt-6-astra\tGPT-6 Astra\tlow high\nacme\\tnova\t\t\n"; out.String() != want {
		t.Errorf("listed %q", out.String())
	}
	listed := `{"models": [{"slug": "gpt-6-astra", "visibility": "list"}]}`
	for _, each := range []struct{ name, listing, exit string }{{"codex failing", listed, "1"},
		{"no JSON", "models", ""}, {"no models", `{"models": null}`, ""},
		{"none listed", `{"models": [{"slug": "gpt-6-luna", "visibility": "hide"}]}`, ""},
		{"a model no object", `{"models": ["gpt-6-astra"]}`, ""},
		{"a level no object", `{"models": [{"slug": "m", "visibility": "list", "supported_reasoning_levels": ["low"]}]}`, ""}} {
		write("listing", each.listing)
		write("exit", each.exit)
		out.Reset()
		if code := Verb("codex", "models")(nil, &out, &errOut); code != 1 || out.Len() != 0 {
			t.Errorf("%s: exit %d, %q", each.name, code, out.String())
		}
	}
}

// codex lists on the login the script's would: an account's own home without the usual login's
// keys; on the usual login the home the caller names, but an account's a seat handed down.
func TestCodexModelsAsksTheLoginsOwnCodex(t *testing.T) {
	home, write := codexListing(t)
	write("listing", `{"models": [{"slug": "gpt-6-astra", "visibility": "list"}]}`)
	t.Setenv("OPENAI_API_KEY", "sk-acme")
	for _, each := range []struct{ account, codexHome, ran string }{
		{"", "", "unset sk-acme "},
		{"", home + "/.codex-b2", "unset sk-acme "},
		{"", "/srv/codex", "/srv/codex sk-acme "},
		{"b2", "/srv/codex", home + "/.codex-b2 unset unset"},
	} {
		t.Setenv("AGENTKIT_ACCOUNT", each.account)
		if t.Setenv("CODEX_HOME", each.codexHome); each.codexHome == "" {
			os.Unsetenv("CODEX_HOME")
		}
		var out, errOut bytes.Buffer
		code := Verb("codex", "models")(nil, &out, &errOut)
		if said := asked(t, home); code != 0 || said != "debug models\n"+each.ran+"\n" {
			t.Errorf("%q on %q: exit %d, asked %q", each.account, each.codexHome, code, said)
		}
	}
}
