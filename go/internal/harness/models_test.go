package harness

import (
	"bytes"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

// listing is a HOME whose program of that name answers with the file `listing` there, exiting as
// the file `exit` says, else 0, and logs each call to `asked`: its words, then what came down its
// stdin; its environment it leaves in `env`.  ask runs that harness's `models`.
func listing(t *testing.T, program string) (home string, write func(path, text string), ask func(harness string) (string, int)) {
	t.Helper()
	if runtime.GOOS == "windows" {
		t.Skip("the fake harness is a shell script")
	}
	home = t.TempDir()
	write = func(path, text string) {
		path = filepath.Join(home, path)
		os.MkdirAll(filepath.Dir(path), 0o700)
		os.WriteFile(path, []byte(text), 0o700)
	}
	write("bin/"+program, `#!/bin/sh
printf '%s\n' "$*" >> "$HOME/asked"
cat >> "$HOME/asked"
env > "$HOME/env"
cat "$HOME/listing" 2>/dev/null
exit $(cat "$HOME/exit" 2>/dev/null || echo 0)
`)
	for key, value := range map[string]string{"HOME": home, "AGENTKIT_ADAPTER_DIR": "", "AGENTKIT_ACCOUNT": "",
		"PATH": filepath.Join(home, "bin") + string(os.PathListSeparator) + os.Getenv("PATH")} {
		t.Setenv(key, value)
	}
	for _, key := range []string{"GROK_HOME", "XDG_CONFIG_HOME"} {
		t.Setenv(key, "")
		os.Unsetenv(key)
	}
	return home, write, func(harness string) (string, int) {
		var out, errOut bytes.Buffer
		code := Verb(harness, "models")(nil, &out, &errOut)
		return out.String() + errOut.String(), code
	}
}

// ran is the environment the fake harness last ran in, by variable.
func ran(t *testing.T, home string) map[string]string {
	t.Helper()
	data, _ := os.ReadFile(filepath.Join(home, "env"))
	env := map[string]string{}
	for _, pair := range strings.Split(string(data), "\n") {
		name, value, _ := strings.Cut(pair, "=")
		env[name] = value
	}
	return env
}

// failsAsItsScript is that harness's `models` failing, saying nothing, where its harness fails
// though it listed, says nothing, or says any of nothing.
func failsAsItsScript(t *testing.T, write func(path, text string), ask func(harness string) (string, int), harness, listed string, nothing ...string) {
	t.Helper()
	write("listing", listed)
	write("exit", "1")
	if said, code := ask(harness); code != 1 || said != "" {
		t.Errorf("%s failing: exit %d, %q", harness, code, said)
	}
	write("exit", "")
	for _, listing := range append(nothing, "") {
		write("listing", listing)
		if said, code := ask(harness); code != 1 || said != "" {
			t.Errorf("%s on %q: exit %d, %q", harness, listing, code, said)
		}
	}
}

// `agy models` folds as the script's awk folds it: each effort-suffixed id into its model, labelled
// as its first line says it without the bracketed effort, its efforts weakest first; an id with no
// suffix runs at `none`.  An account's runs on its own app data, its conversations and brain the
// usual ones, without the usual login's keys or the session bus.
func TestAntigravityModelsFoldsAsItsScript(t *testing.T) {
	home, write, ask := listing(t, "agy")
	write("listing", "gemini-4-neon-high\tGemini 4 Neon (High)\ngemini-4-neon-xhigh\tGemini 4 Neon (XHigh)\n"+
		"gemini-4-neon-low\tGemini 4 Neon (Low)\nclaude-sonnet-4-6\tClaude Sonnet 4.6 (Thinking)\nno label here\ngpt-oss-120b-medium\tGPT-OSS 120B (Medium)\n")
	t.Setenv("GEMINI_API_KEY", "acme-key")
	said, code := ask("antigravity")
	if want := "gemini-4-neon\tGemini 4 Neon\tlow high xhigh\nclaude-sonnet-4-6\tClaude Sonnet 4.6 (Thinking)\tnone\n" +
		"gpt-oss-120b\tGPT-OSS 120B\tmedium\n"; code != 0 || said != want {
		t.Errorf("exit %d: %q", code, said)
	}
	if env := ran(t, home); asked(t, home) != "models\n" || env["GEMINI_API_KEY"] != "acme-key" || env["AGY_CLI_DISABLE_AUTO_UPDATE"] != "1" {
		t.Errorf("the usual login ran on %v", env)
	}
	t.Setenv("AGENTKIT_ACCOUNT", "b2")
	ask("antigravity")
	env := ran(t, home)
	if said := asked(t, home); said != "--app_data_dir=antigravity-cli-b2 models\n" ||
		env["GEMINI_API_KEY"] != "" || env["DBUS_SESSION_BUS_ADDRESS"] != "disabled:" {
		t.Errorf("an account asked %q on %v", said, env)
	}
	for _, store := range []string{"conversations", "brain"} {
		if led, _ := os.Readlink(filepath.Join(home, ".gemini/antigravity-cli-b2", store)); led != "../antigravity-cli/"+store {
			t.Errorf("an account's %s leads to %q", store, led)
		}
	}
	failsAsItsScript(t, write, ask, "antigravity", "gemini-3.8-flash-high\tGemini 3.8 Flash (High)\n", "one field alone\n")
}

// `grok models` names ids alone, each taking the table's label and efforts, one it does not know
// its own id and none; an account's runs on its own Grok home, without the usual login's key.
func TestGrokBuildModelsTakesItsTablesEfforts(t *testing.T) {
	home, write, ask := listing(t, "grok")
	write("listing", "You are logged in with grok.com.\n\nAvailable models:\n  * grok-4.7 (default)\n"+
		"  - grok-4.7-build-fast\n  - acme/nova-1\n  - grok:5 (soon)\n")
	t.Setenv("XAI_API_KEY", "xai-acme")
	said, code := ask("grokbuild")
	if want := "grok-4.7\tgrok-4.7\tlow medium high xhigh\ngrok-4.7-build-fast\tGrok 4.7 Fast\tlow medium high xhigh\n" +
		"acme/nova-1\tacme/nova-1\t\n"; code != 0 || said != want {
		t.Errorf("exit %d: %q", code, said)
	}
	if env := ran(t, home); asked(t, home) != "models\n" || env["XAI_API_KEY"] != "xai-acme" {
		t.Errorf("the usual login ran on %v", env)
	}
	t.Setenv("AGENTKIT_ACCOUNT", "b2")
	if ask("grokbuild"); ran(t, home)["GROK_HOME"] != home+"/.grok-b2" || ran(t, home)["XAI_API_KEY"] != "" {
		t.Errorf("an account ran on %v", ran(t, home))
	}
	t.Setenv("AGENTKIT_ACCOUNT", "")
	failsAsItsScript(t, write, ask, "grokbuild", "  * grok-4.7\n", "Available models:\n  grok-4.7\n")
}

// `muse serve` is sent initialize, initialized and model/list, and the list's answer is written as
// jq's @tsv writes it, efforts that are no list unsaid; an account's runs on its own config home.
func TestMuseModelsAsksItsServer(t *testing.T) {
	home, write, ask := listing(t, "muse")
	write("listing", `{"id": 1, "jsonrpc": "2.0", "result": {"serverInfo": {"name": "muse"}}}
{"id": 2.0, "jsonrpc": "2.0", "result": {"models": [{"modelId": "muse-spark-1.4", "displayLabel": "muse-spark-1.4", "variants": ["low", "high"]}, {"modelId": "muse-spark-lab", "displayLabel": "Muse\tLab", "variants": "unknown"}]}}
`)
	said, code := ask("muse")
	if want := "muse-spark-1.4\tmuse-spark-1.4\tlow high\nmuse-spark-lab\tMuse\\tLab\t\n"; code != 0 || said != want {
		t.Errorf("exit %d: %q", code, said)
	}
	sent := asked(t, home)
	if !strings.HasPrefix(sent, "serve --no-session-log\n") || !strings.HasSuffix(sent, museModelList) {
		t.Errorf("sent %q", sent)
	}
	t.Setenv("META_API_KEY", "meta-acme")
	t.Setenv("AGENTKIT_ACCOUNT", "b2")
	ask("muse")
	if env := ran(t, home); env["XDG_CONFIG_HOME"] != home+"/.muse-b2" || env["META_API_KEY"] != "" || env["MUSE_NO_AUTO_UPDATE"] != "1" {
		t.Errorf("an account ran on %v", env)
	}
	t.Setenv("AGENTKIT_ACCOUNT", "")
	t.Setenv("XDG_CONFIG_HOME", home+"/.muse-b2") // handed down by an account's seat
	if ask("muse"); ran(t, home)["XDG_CONFIG_HOME"] != "" {
		t.Error("the usual login ran on an account's config home")
	}
	failsAsItsScript(t, write, ask, "muse", `{"id": 2, "result": {"models": [{"modelId": "m"}]}}`,
		`{"id": 2, "result": {"models": []}}`, `{"id": 2, "result": {}}`, "[]", `{"id": 2, "result": {"models": [7]}}`)
}

// OpenCode's list is each enabled model's `provider/model`, name and variants, `none` for none and
// a `mimo/` model's unsaid, through the table, which knows MiMo's; an account is refused.
func TestOpenCodeModelsListsThroughItsTable(t *testing.T) {
	_, write, ask := listing(t, "opencode")
	write("listing", `{"data": [
  {"providerID": "opencode", "id": "beam-free", "name": "Beam Free", "variants": [{"id": "low"}, {"id": "max"}]},
  {"providerID": "opencode", "id": "big-pickle", "enabled": true, "variants": []},
  {"providerID": "opencode", "id": "off", "enabled": false},
  {"providerID": "mimo", "id": "mimo-v2.6-pro", "name": "mimo-v2.6-pro", "variants": [{"id": "low"}]},
  {"providerID": "mimo", "id": "mimo-v9", "name": "mimo-v9"}]}`)
	said, code := ask("opencode")
	if want := "opencode/beam-free\tBeam Free\tlow max\nopencode/big-pickle\tbig-pickle\tnone\n" +
		"mimo/mimo-v2.6-pro\tMiMo V2.6 Pro\tnone high\nmimo/mimo-v9\tmimo-v9\t\n"; code != 0 || said != want {
		t.Errorf("exit %d: %q", code, said)
	}
	t.Setenv("AGENTKIT_ACCOUNT", "b2")
	if said, code := ask("opencode"); code != 1 || !strings.HasPrefix(said, "opencode: account b2 refused; ") {
		t.Errorf("an account: exit %d, %q", code, said)
	}
	t.Setenv("AGENTKIT_ACCOUNT", "")
	failsAsItsScript(t, write, ask, "opencode", `{"data": [{"providerID": "opencode", "id": "m"}]}`,
		`{"data": []}`, `{"data": [{"providerID": "opencode", "id": "off", "enabled": false}]}`, "[]", `{"data": [7]}`)
}

// Where PATH finds no harness, each runs the one its installer put in its folder, as its script's
// header does, that folder ahead of PATH for what it runs in turn: a launcher finds what is beside it.
func TestModelsRunTheHarnessItsInstallerPut(t *testing.T) {
	for harness, each := range map[string]struct{ program, folder, listed, want string }{
		"antigravity": {"agy", ".local/bin", "acme-1-high\tAcme 1 (High)\n", "acme-1\tAcme 1\thigh\n"},
		"grokbuild":   {"grok", ".grok/bin", "  * acme-1\n", "acme-1\tacme-1\t\n"},
		"muse": {"muse", ".local/bin", `{"id": 2, "result": {"models": [{"modelId": "acme-1", "displayLabel": "Acme 1"}]}}`,
			"acme-1\tAcme 1\t\n"},
		"opencode": {"opencode", ".opencode/bin", `{"data": [{"providerID": "acme", "id": "acme-1", "name": "Acme 1"}]}`,
			"acme/acme-1\tAcme 1\tnone\n"},
	} {
		t.Run(harness, func(t *testing.T) {
			home, write, ask := listing(t, each.program)
			write("listing", each.listed)
			os.MkdirAll(filepath.Join(home, each.folder), 0o700)
			os.Rename(filepath.Join(home, "bin", each.program), filepath.Join(home, each.folder, "acme-lister"))
			write(filepath.Join(each.folder, each.program), "#!/bin/sh\nexec acme-lister \"$@\"\n")
			// a PATH holding only what the fake runs, so no harness installed here answers
			for _, tool := range []string{"cat", "env"} {
				found, _ := exec.LookPath(tool)
				os.Symlink(found, filepath.Join(home, "bin", tool))
			}
			t.Setenv("PATH", filepath.Join(home, "bin"))
			if said, code := ask(harness); code != 0 || said != each.want {
				t.Errorf("exit %d: %q", code, said)
			}
			if path := ran(t, home)["PATH"]; path != filepath.Join(home, each.folder)+string(os.PathListSeparator)+filepath.Join(home, "bin") {
				t.Errorf("ran on PATH %q", path)
			}
		})
	}
}
