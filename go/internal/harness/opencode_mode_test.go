package harness

import (
	"os"
	"path/filepath"
	"runtime"
	"testing"

	"agentkit/internal/config"
)

// Each answer is Python's opencode.mode on the same opencode.json.
func TestMimoIsAPlanOnlyWhereOpencodeJSONSendsItToOne(t *testing.T) {
	const plan = `"https://token-plan-ams.xiaomimimo.com/v1"`
	t.Setenv("OPENCODE_CONFIG", "")
	legacy := func(url string) string { return `{"provider":{"mimo":{"options":{"baseURL":` + url + `}}}}` }
	for _, each := range []struct{ doc, want string }{
		{legacy(plan), "subscription"},
		{`{"providers":{"mimo":{"settings":{"baseURL":"https://token-plan-sgp.xiaomimimo.com/v1"}}}}`, "subscription"},
		{legacy(`"HTTPS://Token-Plan-ams.XiaomiMiMo.com:443/v1"`), "subscription"},
		{legacy(`" https://token-plan-ams.xiaomimimo.com\n/v1"`), "subscription"},
		{`{"providers":{"mimo":{"settings":{"baseURL":` + plan + `}}},"provider":{"mimo":{"options":{"baseURL":` + plan + `}}}}`, "subscription"},
		{legacy(`"https://api.xiaomimimo.com/v1"`), "payg"},
		{legacy(`"http://token-plan-ams.xiaomimimo.com/v1"`), "payg"},
		{legacy(`"https://me@token-plan-ams.xiaomimimo.com/v1"`), "payg"},
		{legacy(`"https://token-plan-ams.xiaomimimo.com:x/v1"`), "payg"},
		{legacy(`"https://token-plan-ams.xiaomimimo.com:70000/v1"`), "payg"},
		{legacy(`"https://[token-plan-ams.xiaomimimo.com]/v1"`), "payg"},
		{legacy(`"{env:MIMO_URL}"`), "payg"},
		{`{"provider":{"mimo":{"options":{"baseURL":` + plan + `},"models":{"x":{"api":"https://api.xiaomimimo.com/v1"}}}}}`, "payg"},
		{`{"providers":{"mimo":{"settings":{"baseURL":""}}},"provider":{"mimo":{"options":{"baseURL":` + plan + `}}}}`, "payg"},
		{`{"provider":{"mimo":{}}}`, "payg"},
		{`{`, "payg"},
	} {
		folder := t.TempDir()
		t.Setenv("OPENCODE_CONFIG_DIR", folder)
		if err := os.WriteFile(filepath.Join(folder, "opencode.json"), []byte(each.doc), 0o600); err != nil {
			t.Fatal(err)
		}
		if got := Mode(config.Model{Harness: "opencode", ID: "mimo/mimo-v2.6-pro"}); got != each.want {
			t.Errorf("%s: %q, want %q", each.doc, got, each.want)
		}
	}
}

func TestMimoIsPaygWhereAnythingElseMayBeRead(t *testing.T) {
	mimo := config.Model{Harness: "opencode", ID: "mimo/mimo-v2.6-pro"}
	t.Setenv("OPENCODE_CONFIG", "")
	folder := t.TempDir()
	t.Setenv("OPENCODE_CONFIG_DIR", folder)
	if got := Mode(mimo); got != "payg" {
		t.Errorf("no opencode.json: %q", got)
	}
	doc := `{"provider":{"mimo":{"options":{"baseURL":"https://token-plan-ams.xiaomimimo.com/v1"}}}}`
	if err := os.WriteFile(filepath.Join(folder, "opencode.json"), []byte(doc), 0o600); err != nil {
		t.Fatal(err)
	}
	if got := Mode(config.Model{Harness: "opencode", ID: "zeta/coder"}); got != "" {
		t.Errorf("a model of another provider: %q", got)
	}
	t.Setenv("OPENCODE_CONFIG", filepath.Join(folder, "acme.json"))
	if got := Mode(mimo); got != "payg" {
		t.Errorf("OPENCODE_CONFIG set: %q", got)
	}
	t.Setenv("OPENCODE_CONFIG", "")
	if err := os.WriteFile(filepath.Join(folder, "opencode.jsonc"), []byte("{}"), 0o600); err != nil {
		t.Fatal(err)
	}
	if got := Mode(mimo); got != "payg" {
		t.Errorf("an opencode.jsonc beside it: %q", got)
	}
}

// A `..` after a link leads out of the link's target, as OpenCode and the adapter's shell walk
// it, never to the folder beside the link that cleaning the path's text leads to.
func TestMimoIsReadWhereTheSystemWalksItsFolder(t *testing.T) {
	if runtime.GOOS == "windows" {
		t.Skip("Windows takes `..` out of a path before it follows a link")
	}
	root := t.TempDir()
	if err := os.MkdirAll(filepath.Join(root, "remote", "child"), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink(filepath.Join(root, "remote", "child"), filepath.Join(root, "current")); err != nil {
		t.Fatal(err)
	}
	// the plan where the system walks, a paid endpoint where cleaning the text leads
	for base, url := range map[string]string{filepath.Join(root, "remote"): "https://token-plan-ams.xiaomimimo.com/v1",
		root: "https://api.xiaomimimo.com/v1"} {
		for _, folder := range []string{"opencode", filepath.Join(".config", "opencode")} {
			doc := `{"provider":{"mimo":{"options":{"baseURL":"` + url + `"}}}}`
			if err := os.MkdirAll(filepath.Join(base, folder), 0o700); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(filepath.Join(base, folder, "opencode.json"), []byte(doc), 0o600); err != nil {
				t.Fatal(err)
			}
		}
	}
	link := root + "/current/.."
	for key, value := range map[string]string{"OPENCODE_CONFIG_DIR": link + "/opencode", "XDG_CONFIG_HOME": link, "HOME": link} {
		for _, other := range []string{"OPENCODE_CONFIG", "OPENCODE_CONFIG_DIR", "XDG_CONFIG_HOME"} {
			t.Setenv(other, "")
		}
		t.Setenv("HOME", t.TempDir())
		t.Setenv(key, value)
		if got := Mode(config.Model{Harness: "opencode", ID: "mimo/mimo-v2.6-pro"}); got != "subscription" {
			t.Errorf("%s=%s: %q, want the plan where the system walks", key, value, got)
		}
	}
}
