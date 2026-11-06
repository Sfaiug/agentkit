package browser

import (
	"io"
	"net/http"
	"net/http/httptest"
	"slices"
	"strings"
	"testing"
)

// Tidy asks DevTools through the proxy Python's urllib picks, a bare host:port among them, as
// Python's tidy does; one carrying a login is Python's, asked nothing.
func TestTidyAsksThroughThePythonsProxy(t *testing.T) {
	machine(t)
	seen := make(chan string, 10)
	proxy := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		seen <- r.URL.String()
		if r.URL.Path == "/json/list" {
			io.WriteString(w, `[{"id": "A", "type": "page"}, {"id": "B", "type": "page"}]`)
		}
	}))
	t.Cleanup(proxy.Close)
	CDP = "http://devtools.acme.test:9222" // only the proxy reaches it; machine puts it back
	t.Setenv("AK_BROWSER_TAB_CAP", "1")
	host := strings.TrimPrefix(proxy.URL, "http://")
	t.Setenv("http_proxy", host)
	if !Tidy(1e9, func(string) {}) {
		t.Fatal("left to Python")
	}
	t.Setenv("http_proxy", "http://acme:secret@"+host)
	if Tidy(1e9, func(string) {}) {
		t.Fatal("a proxy with a login carried")
	}
	close(seen)
	var asked []string
	for each := range seen {
		asked = append(asked, each)
	}
	if !slices.Equal(asked, []string{CDP + "/json/list", CDP + "/json/close/B"}) {
		t.Fatal(asked)
	}
}
