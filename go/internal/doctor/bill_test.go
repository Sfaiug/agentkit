//go:build unix

package doctor

import (
	"bytes"
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
	"time"
)

// While ak may rent, the lines are the tick's last answer and what it said of the machines it
// gave back, each as Python's google_cloud.said words it, an answer older than two passes in
// local time.
func TestDoctorShowsTheBillWhileAkMayRent(t *testing.T) {
	local := time.Local
	time.Local = time.FixedZone("CET", 3600)
	t.Cleanup(func() { time.Local = local })
	now := time.Date(2026, 11, 1, 3, 0, 0, 0, time.UTC).Unix()
	late := `["acme-3 listed past its end, given back", "acme-4 listed past the cap, not given back: Google refused: Forbidden"]`
	for name, each := range map[string]struct {
		ledger, late string
		want         []string
	}{
		"answered just now": {
			fmt.Sprintf(`{"answered": %d, "spent": 7.25, "machines": {"1": {"price": 6.0045, "until": %d},
				"acme-2": {"price": 1, "from": %d, "until": %d}}}`, now, now+3600, now-60, now+3600), late,
			[]string{"1 running · €7.25 of €50.00 this month", "acme-3 listed past its end, given back",
				"acme-4 listed past the cap, not given back: Google refused: Forbidden"}},
		"answered seven minutes ago": {
			fmt.Sprintf(`{"answered": %d, "spent": 3, "machines": {}}`, now-420), "[]",
			[]string{"0 running · €3.00 of €50.00 this month as of 1 Nov 03:53"}},
		"cannot be read": {"{", late, []string{
			"cannot read ~/.agentkit/state/google-cloud-ledger.json: all machines go back",
			"acme-3 listed past its end, given back",
			"acme-4 listed past the cap, not given back: Google refused: Forbidden"}},
		"no answer yet": {"", late, []string{"Google has not answered the tick yet"}},
	} {
		t.Run(name, func(t *testing.T) {
			root, adapters := home(t, models+"\n[google_cloud]\nactive = true\nmax_month = 50\n")
			os.WriteFile(filepath.Join(adapters, "acme.sh"), []byte("#!/bin/sh\nprintf 'acme-1\\tAcme 1\\thigh\\n'\n"), 0o755)
			state := filepath.Join(root, ".agentkit", "state")
			os.MkdirAll(state, 0o700)
			os.WriteFile(filepath.Join(state, "clock"), []byte(fmt.Sprint(now)), 0o600)
			t.Setenv("AK_GOOGLE_CLOCK", filepath.Join(state, "clock"))
			if each.ledger != "" {
				os.WriteFile(filepath.Join(state, "google-cloud-ledger.json"), []byte(each.ledger), 0o600)
			}
			os.WriteFile(filepath.Join(state, "google-cloud-late.json"), []byte(each.late), 0o600)
			var out, errOut bytes.Buffer
			if _, read := Report(&out, &errOut); !read {
				t.Fatalf("left to Python: stderr=%q", errOut.String())
			}
			var got []string
			for _, line := range strings.Split(out.String(), "\n") {
				if said, ok := strings.CutPrefix(line, "rented machines: "); ok {
					got = append(got, said)
				}
			}
			if !slices.Equal(got, each.want) {
				t.Fatalf("got %q, want %q", got, each.want)
			}
		})
	}
}
