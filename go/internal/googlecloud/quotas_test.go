package googlecloud

import (
	"crypto/rand"
	"crypto/rsa"
	"crypto/x509"
	"encoding/json"
	"encoding/pem"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"slices"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"
)

// An offer past its family's limit, its family's _CPUS quota, its region's CPUS or all regions' is
// passed over and said, every machine Google lists counted, ak's or not, and a limit of -1 holds
// nothing; limits that cannot be read leave the walk as before. The first skipped offer's due
// quotas are asked for, by POST, or by PATCH with the preference's name and etag; one asked within
// the day is not. Each ask, a refusal, a grant short and an unreadable preference list are said as
// Python says them, and a rent that skips nothing asks nothing.
func TestARentPassesOverFullQuotasAndAsksForWhatItLacks(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	ak := filepath.Join(home, ".agentkit")
	write := func(name, text string) {
		t.Helper()
		path := filepath.Join(ak, name)
		if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(text), 0o600); err != nil {
			t.Fatal(err)
		}
	}
	private, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatal(err)
	}
	der, _ := x509.MarshalPKCS8PrivateKey(private)
	key, _ := json.Marshal(map[string]string{"project_id": "acme-build", "client_email": "ak@acme-build.example",
		"private_key": string(pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: der}))})
	write("secrets/google-cloud.json", string(key))
	write("secrets/google-cloud-ssh", "a key\n")
	write("secrets/google-cloud-ssh.pub", "ssh-ed25519 AAAAacme ak\n")
	t.Setenv("AK_GOOGLE_CLOCK", filepath.Join(ak, "clock"))
	t.Cleanup(func() { unanswered = nil })

	const midnight = 1793577600.0 // 2 Nov 2026, 00:00 UTC
	// a vCPU €0.10 an hour in europe-west4, €0.125 in us-central1
	write("state/google-cloud-offers.json", `{"at": 1793577540.0, "offers": [
		["c4a-highcpu-16", "europe-west4", 16, 32768, 1.6, ["europe-west4-a"], "projects/debian-cloud/global/images/family/debian-13-arm64", "hyperdisk-balanced"],
		["c4a-highcpu-8", "us-central1", 8, 16384, 1.0, ["us-central1-a"], "projects/debian-cloud/global/images/family/debian-13-arm64", "hyperdisk-balanced"]]}`)

	// Google: a token for any JWT; 16 vCPUs of ak's and 8 of another's listed in europe-west4, and 8
	// of another's in us-east5, where nothing is offered; each create made; Service Usage's family
	// limits, unanswered where silent; each region's quotas and the project's; Cloud Quotas' list of
	// preferences, and each ask of it kept, a request whose quotaId, or "list", refusing names
	// answered with that status, or 0 silence.
	const (
		project = "/compute/v1/projects/acme-build"
		quotas  = "/v1/projects/acme-build/locations/global/quotaPreferences"
		created = `"creationTimestamp": "2026-11-01T23:00:00Z"`
	)
	var held sync.Mutex
	var made []map[string]any
	var asked []string
	var asks [][]byte
	var families, preferences string
	var regions map[string]string
	var refusing map[string]int
	silent := func(w http.ResponseWriter) {
		conn, _, _ := w.(http.Hijacker).Hijack()
		conn.Close()
	}
	google := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		held.Lock()
		defer held.Unlock()
		answer := func(refused, body string) {
			code, ok := refusing[refused]
			switch {
			case !ok:
				io.WriteString(w, body)
			case code == 0:
				silent(w)
			default:
				http.Error(w, "{}", code)
			}
		}
		path := strings.TrimPrefix(r.URL.Path, project)
		switch {
		case path == "/token":
			io.WriteString(w, `{"access_token": "ya29.acme"}`)
		case path == "/aggregated/instances":
			io.WriteString(w, `{"items": {"zones/europe-west4-a": {"instances": [
				{"id": "1", "name": "ak-aaa", "labels": {"ak": "rented"}, `+created+`,
					"machineType": "zones/europe-west4-a/machineTypes/c4a-highcpu-16", "scheduling": {"maxRunDuration": {"seconds": "21600"}}},
				{"id": "2", "name": "acme-2", "labels": {"team": "acme"}, `+created+`, "machineType": "zones/europe-west4-a/machineTypes/c4a-highcpu-8"}]},
				"zones/us-east5-a": {"instances": [{"id": "3", "name": "acme-3", `+created+`, "machineType": "zones/us-east5-a/machineTypes/c4a-highcpu-8"}]}}}`)
		case r.Method == http.MethodPost && strings.HasSuffix(path, "/instances"):
			var body map[string]any
			json.NewDecoder(r.Body).Decode(&body)
			made = append(made, body)
			io.WriteString(w, `{"status": "DONE"}`)
		case strings.HasSuffix(path, "/compute.googleapis.com/cpus_per_vm_family") && families == "silent":
			silent(w)
		case strings.HasSuffix(path, "/compute.googleapis.com/cpus_per_vm_family"):
			io.WriteString(w, `{"consumerQuotaLimits": [{"quotaBuckets": [`+families+`]}]}`)
		case path == "" || strings.HasPrefix(path, "/regions/"):
			io.WriteString(w, `{"quotas": [`+regions[strings.TrimPrefix(path, "/regions/")]+`]}`)
		case r.URL.Path == quotas && r.Method == http.MethodGet:
			asked = append(asked, "list")
			answer("list", `{"quotaPreferences": [`+preferences+`]}`)
		case strings.HasPrefix(r.URL.Path, quotas):
			data, _ := io.ReadAll(r.Body)
			var ask struct {
				Name, Etag, QuotaID string
				Dimensions          map[string]string
				QuotaConfig         struct{ PreferredValue string }
			}
			json.Unmarshal(data, &ask)
			one := fmt.Sprint(r.Method, " ", ask.QuotaID, " ", ask.QuotaConfig.PreferredValue, " ", ask.Dimensions)
			if r.Method == http.MethodPatch {
				one += fmt.Sprintf(" at %s?%s by %s %s", r.URL.Path, r.URL.RawQuery, ask.Name, ask.Etag)
			}
			asked, asks = append(asked, one), append(asks, data)
			answer(ask.QuotaID, `{}`)
		default:
			http.NotFound(w, r)
		}
	}))
	defer google.Close()
	t.Setenv("AK_GOOGLE_URL", google.URL)

	bucket := func(region, limit string) string { // Google leaves a limit of 0 out
		if limit != "" {
			limit = `"effectiveLimit": "` + limit + `", `
		}
		return `{` + limit + `"dimensions": {"region": "` + region + `", "vm_family": "C4A"}}`
	}
	quota := func(metric string, limit float64) string {
		return fmt.Sprintf(`{"metric": %q, "limit": %.1f}`, metric, limit)
	}
	const family, all = "CPUS-PER-VM-FAMILY-per-project-region", "CPUS-ALL-REGIONS-per-project"
	nl, us := `{"region": "europe-west4", "vm_family": "C4A"}`, `{"region": "us-central1", "vm_family": "C4A"}`
	// Cloud Quotas' preference of a quota, updated ago seconds and a nanosecond's fraction before
	// midnight, as it writes the time
	kept := func(name, id, dimensions string, ago float64, reconciling bool, config string) string {
		return fmt.Sprintf(`{"name": "projects/acme-build/locations/global/quotaPreferences/%s", "service": "compute.googleapis.com",
			"etag": "e7", "quotaId": %q, "dimensions": %s, "updateTime": %q, "reconciling": %t, "quotaConfig": %s}`, name, id,
			dimensions, time.Unix(int64(midnight-ago), 123).UTC().Format(time.RFC3339Nano), reconciling, config)
	}
	// europe-west4's C4A 32 vCPUs, us-central1's 0 and all regions' 40: the cheapest, past both, and
	// the next, past its family's, are passed over
	full := bucket("europe-west4", "32") + ", " + bucket("us-central1", "")
	short := map[string]string{"": quota("CPUS_ALL_REGIONS", 40)}
	const (
		passed  = "too little quota left: C4A in europe-west4: 24 of 32 vCPUs in use; CPUS_ALL_REGIONS: 32 of 40 vCPUs in use; C4A in us-central1: 0 of 0 vCPUs in use"
		askedNL = "C4A in europe-west4: 40 vCPUs asked of Google, the limit now 32"
		posted  = "POST " + family + " 40 map[region:europe-west4 vm_family:C4A]"
	)

	for _, c := range []struct {
		name, families string
		regions        map[string]string
		preferences    string
		refusing       map[string]int
		said, asked    []string // the machine rented named ak-new
	}{
		{name: "a family's limit", families: bucket("europe-west4", "32") + ", " + bucket("us-central1", "8"),
			said:  []string{"ak-new rented: c4a-highcpu-8 in us-central1-a", askedNL},
			asked: []string{"list", posted}},
		{name: "a family's _CPUS and a region's CPUS, where Google lists no family limit",
			regions: map[string]string{"europe-west4": quota("C4A_CPUS", 30) + ", " + quota("CPUS", 1000), "us-central1": quota("CPUS", 4)},
			said: []string{"too little quota left: C4A_CPUS in europe-west4: 24 of 30 vCPUs in use; CPUS in us-central1: 0 of 4 vCPUs in use",
				"C4A_CPUS in europe-west4: 40 vCPUs asked of Google, the limit now 30"},
			asked: []string{"list", "POST C4A-CPUS-per-project-region 40 map[region:europe-west4]"}},
		{name: "all regions', a family's -1 holding nothing", families: bucket("europe-west4", "-1"),
			regions: map[string]string{"europe-west4": quota("CPUS", 0), "": quota("CPUS_ALL_REGIONS", 40)},
			said:    []string{"ak-new rented: c4a-highcpu-8 in us-central1-a", "CPUS_ALL_REGIONS: 48 vCPUs asked of Google, the limit now 40"},
			asked:   []string{"list", "POST " + all + " 48 map[]"}},
		{name: "-1 everywhere", families: bucket("europe-west4", "-1"), regions: map[string]string{"": quota("CPUS_ALL_REGIONS", -1)},
			said: []string{"ak-new rented: c4a-highcpu-16 in europe-west4-a"}},
		{name: "limits unread", families: "silent", regions: map[string]string{"europe-west4": quota("CPUS", 0)},
			said: []string{"ak-new rented: c4a-highcpu-16 in europe-west4-a"}},
		{name: "one asked a day ago changed by its etag, one within the day not, a grant short said", families: full, regions: short,
			preferences: kept("c4a-nl", family, nl, 86400, true, `{"preferredValue": "40", "grantedValue": "32"}`) + ", " +
				kept("all", all, "{}", 86399, false, `{"preferredValue": "48", "grantedValue": "48"}`) + ", " +
				kept("c4a-us", family, us, 3600, false, `{"preferredValue": "16"}`) + `, {"service": "storage.googleapis.com",
					"quotaId": "x", "updateTime": "2026-11-01T00:00:00Z", "quotaConfig": {"preferredValue": "9"}}`,
			said: []string{passed, "C4A in us-central1: Google granted 0 of the 16 vCPUs asked", askedNL},
			asked: []string{"list", "PATCH " + family + " 40 map[region:europe-west4 vm_family:C4A] at " + quotas + "/c4a-nl?" +
				"updateMask=quotaConfig.preferredValue,contactEmail,justification by " + quotas[4:] + "/c4a-nl e7"}},
		{name: "the cheapest's all asked within the day", families: full, regions: short,
			preferences: kept("c4a-nl", family, nl, 3600, true, `{"preferredValue": "40"}`) + ", " +
				kept("all", all, "{}", 3600, true, `{"preferredValue": "48"}`),
			said:  []string{passed, "C4A in us-central1: 8 vCPUs asked of Google, the limit now 0"},
			asked: []string{"list", "POST " + family + " 8 map[region:us-central1 vm_family:C4A]"}},
		{name: "an ask unanswered and one refused", families: full, regions: short, refusing: map[string]int{family: 0, all: 403},
			said: []string{passed, askedNL + ": asking Google failed: EOF",
				"CPUS_ALL_REGIONS: 48 vCPUs asked of Google, the limit now 40: Google refused: Forbidden"},
			asked: []string{"list", posted, "POST " + all + " 48 map[]"}},
		{name: "the list refused", families: full, regions: short, refusing: map[string]int{"list": 403},
			said: []string{passed, "no quota asked for: Google refused: Forbidden"}, asked: []string{"list"}},
	} {
		held.Lock()
		families, regions, preferences, refusing = c.families, c.regions, c.preferences, c.refusing
		start, asking := len(made), len(asked)
		held.Unlock()
		write("clock", strconv.FormatFloat(midnight, 'f', -1, 64))
		write("config.toml", "[google_cloud]\nactive = true\nmax_month = 100\n")
		write("state/google-cloud-need", "820 tests\n")
		os.Remove(meterPath()) // what each pass rents comes up no longer
		carried, err := Watch("")
		held.Lock()
		creates, got := made[start:], slices.Clone(asked[asking:])
		held.Unlock()
		data, _ := os.ReadFile(latePath())
		var said []string
		json.Unmarshal(data, &said)
		if len(creates) > 0 {
			for n := range said {
				said[n] = strings.ReplaceAll(said[n], fmt.Sprint(creates[0]["name"]), "ak-new")
			}
		}
		if !carried || err != nil || len(creates) > 1 || !slices.Equal(said, c.said) || !slices.Equal(got, c.asked) {
			t.Errorf("%s: carried %v, %v, said %q, asking %q", c.name, carried, err, said, got)
		}
	}

	// asked as Python asks
	var python, first map[string]any
	json.Unmarshal([]byte(`{"service": "compute.googleapis.com", "quotaId": "CPUS-PER-VM-FAMILY-per-project-region",
		"dimensions": {"region": "europe-west4", "vm_family": "C4A"}, "quotaConfig": {"preferredValue": "40"},
		"contactEmail": "ak@acme-build.example",
		"justification": "Spot machines running this project's test suites: the vCPUs in use plus one more machine"}`), &python)
	if json.Unmarshal(asks[0], &first); !reflect.DeepEqual(first, python) {
		t.Errorf("asked %s", asks[0])
	}
}
