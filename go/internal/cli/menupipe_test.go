package cli

import (
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestAPipedLocalMenuPrintsItsNoticeAndOneCompactFrame(t *testing.T) {
	in, err := os.Open(os.DevNull)
	if err != nil {
		t.Fatal(err)
	}
	defer in.Close()
	previous := os.Stdin
	os.Stdin = in
	defer func() { os.Stdin = previous }()
	t.Setenv("PATH", t.TempDir())
	t.Setenv("COLUMNS", "80")
	for _, each := range []struct {
		name, server string
		args         []string
	}{
		{name: "bare"},
		{name: "client", args: []string{"--client"}},
		{name: "dry", args: []string{"--dry-run"}},
		{name: "overlay", server: "acme-box\n", args: []string{"--overlay"}},
	} {
		t.Run(each.name, func(t *testing.T) {
			home := clientHome(t, each.server)
			notice := filepath.Join(home, ".agentkit", "state", "update-result")
			write(t, notice, "update: done\n")
			var out, errOut bytes.Buffer
			code := Main(each.args, &out, &errOut)
			if code != 0 || errOut.Len() != 0 {
				t.Fatalf("exit=%d stderr=%q", code, errOut.String())
			}
			text := out.String()
			if !strings.HasPrefix(text, " update: done\nagentkit") || !strings.Contains(text, "no sessions; n starts one") ||
				!strings.HasSuffix(strings.TrimSpace(text), "esc leave") {
				t.Fatalf("incomplete menu: %.2000q", text)
			}
			if rows := strings.Count(text, "\n"); rows > 20 {
				t.Fatalf("an empty menu printed %d rows", rows)
			}
			if _, err := os.Stat(notice); !os.IsNotExist(err) {
				t.Fatalf("notice was not consumed: %v", err)
			}
		})
	}
}
