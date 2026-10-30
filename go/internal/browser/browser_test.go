package browser

import (
	"bytes"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// A machine without systemd or the desktop's tools, whose DevTools answers version and list.
func machine(t *testing.T) (version, list *string) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	t.Setenv("PATH", t.TempDir())
	for _, name := range []string{"http_proxy", "HTTP_PROXY", "no_proxy", "NO_PROXY"} {
		t.Setenv(name, "")
	}
	version, list = new(string), new(string)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		io.WriteString(w, map[string]string{"/json/version": *version, "/json/list": *list}[r.URL.Path])
	}))
	t.Cleanup(server.Close)
	was, wasDir := cdp, unitDir
	cdp, unitDir = server.URL, t.TempDir()
	t.Cleanup(func() { cdp, unitDir = was, wasDir })
	records := fmt.Sprintf(`{"A": {"last_change": %d}}`, time.Now().Unix()-7300)
	if err := os.MkdirAll(filepath.Join(home, ".agentkit", "state"), 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(home, ".agentkit", "state", "browser-tabs.json"), []byte(records), 0o600); err != nil {
		t.Fatal(err)
	}
	return version, list
}

func TestTabsAreCutAndPaddedByCodePoint(t *testing.T) {
	version, list := machine(t)
	*version = `{"Browser": 140}`
	*list = `[{"id": "A", "type": "page", "title": "` + strings.Repeat("é", 61) + `", "url": "https://acme.test/` + strings.Repeat("ü", 80) + `"},
	          {"id": "B", "type": "page", "title": " \ud800 docs "}, {"id": "F", "type": "iframe"}]`
	var out bytes.Buffer
	if code, err := Status(&out); code != 0 || err != nil {
		t.Fatalf("exit %d, %v", code, err)
	}
	want := strings.Join([]string{
		"units      no systemd on this machine; the stack lives on the server",
		"mcp        no systemd on this machine; the shared server lives on the server",
		"cdp        " + cdp + " reachable, 140",
		"tabs       2 open (cap 12; a tab idle 60 min is closed by ak watch)",
		"  " + strings.Repeat("é", 60) + " https://acme.test/" + strings.Repeat("ü", 62) + " idle 2h",
		// a lone surrogate, which Python's print cannot write, is U+FFFD
		"  � docs" + strings.Repeat(" ", 54) + "  idle 0m",
		"desktop    DISPLAY=:99, missing xdotool, imagemagick",
		"novnc      no address recorded; the noVNC unit is not installed here",
	}, "\n") + "\n"
	if out.String() != want {
		t.Fatalf("got\n%s\nwant\n%s", out.String(), want)
	}
}

type closed struct{}

func (closed) Write([]byte) (int, error) { return 0, errors.New("broken pipe") }

func TestAClosedStdoutEndsItWithZero(t *testing.T) {
	version, list := machine(t)
	*version, *list = `{}`, `[]`
	if code, err := Status(closed{}); code != 0 || err != nil {
		t.Fatalf("exit %d, %v", code, err)
	}
}

func TestWhatPythonReadsOtherwiseIsPythonsAndPrintsNothing(t *testing.T) {
	version, list := machine(t)
	for _, answers := range [][2]string{
		{`[]`, `[]`}, // Python's .get on a list
		{`{}`, `{"A": {}}`},
		{`{}`, `[1]`},
		{`{}`, `[{"type": "page", "title": 5}]`},
		{`{}`, `[{"type": "page", "url": null}]`},
		{`{}`, `[{"type": "page", "id": ["A"]}]`},
		{`{}`, strings.Repeat("[", 600) + strings.Repeat("]", 600)}, // past Python's recursion
	} {
		*version, *list = answers[0], answers[1]
		var out bytes.Buffer
		if _, err := Status(&out); !errors.Is(err, ErrPython) || out.Len() != 0 {
			t.Errorf("%s %s: %v, printed %q", answers[0], answers[1], err, out.String())
		}
	}
}

func TestAProxyPythonSendsDevToolsThroughIsPythons(t *testing.T) {
	version, list := machine(t)
	*version, *list = `{}`, `[]`
	t.Setenv("http_proxy", "http://proxy.acme.test:3128")
	for bypass, left := range map[string]bool{"": true, "acme.test, .127.0.0.1": false, "*": false, "0.0.1": false, "127.0.0.0/8": true} {
		t.Setenv("no_proxy", bypass)
		var out bytes.Buffer
		if _, err := Status(&out); errors.Is(err, ErrPython) != left {
			t.Errorf("no_proxy=%q: %v, printed %q", bypass, err, out.String())
		}
	}
}
