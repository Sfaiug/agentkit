package googlecloud

import (
	"crypto/rand"
	"crypto/rsa"
	"crypto/x509"
	"encoding/json"
	"encoding/pem"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"sync"
	"testing"
)

// Each pass meters what Google lists, from the last answer or a machine's creation, at the dearer
// of the price held and the price offered, and gives back each machine past its end, with no price
// kept, past the cap or, with no work marked, unused, saying each, in Python's records; a need to
// rent for is left to Python with nothing written, unless the cap leaves nothing to rent with.
func TestTheTickMetersRentalsAndGivesBackThoseItMayNotKeep(t *testing.T) {
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
	read := func(name string) string {
		data, _ := os.ReadFile(filepath.Join(ak, name))
		return string(data)
	}
	gone := func(name string) bool {
		_, err := os.Stat(filepath.Join(ak, name))
		return os.IsNotExist(err)
	}
	private, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatal(err)
	}
	der, _ := x509.MarshalPKCS8PrivateKey(private)
	key, _ := json.Marshal(map[string]string{"project_id": "acme-build", "client_email": "ak@acme-build.example",
		"private_key": string(pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: der}))})
	write("secrets/google-cloud.json", string(key))
	t.Setenv("AK_GOOGLE_CLOCK", filepath.Join(ak, "clock"))
	t.Cleanup(func() { unanswered = nil })

	// Google: a token for any JWT; ak's machines listed by zone, or the listing refused while
	// refusing; each machine read and deleted by name, unless its deletion is refused; and a price
	// list of one type. What a pass asked is each method and path, a machine's by its name.
	const project = "/compute/v1/projects/acme-build"
	var held sync.Mutex
	var listing []map[string]any
	refused, refusing, asked := map[string]bool{}, false, []string{}
	sku := func(description, region string, nanos int, unit string) map[string]any {
		return map[string]any{"description": description, "serviceRegions": []string{region}, "pricingInfo": []any{
			map[string]any{"pricingExpression": map[string]any{"usageUnit": unit, "tieredRates": []any{
				map[string]any{"unitPrice": map[string]any{"units": "0", "nanos": nanos}}}}}}}
	}
	google := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		held.Lock()
		defer held.Unlock()
		answer := func(body any) { json.NewEncoder(w).Encode(body) }
		path := strings.TrimPrefix(r.URL.Path, project)
		name := path[strings.LastIndexByte(path, '/')+1:]
		at := slices.IndexFunc(listing, func(one map[string]any) bool { return one["name"] == name })
		switch {
		case path == "/token":
			answer(map[string]string{"access_token": "ya29.acme"})
			return
		case strings.Contains(path, "/instances/"):
			asked = append(asked, r.Method+" "+name)
		default:
			asked = append(asked, r.Method+" "+path)
		}
		switch {
		case path == "/aggregated/instances" && refusing:
			http.Error(w, "{}", http.StatusForbidden)
		case path == "/aggregated/instances":
			items := map[string]map[string][]any{}
			for _, one := range listing {
				zone := "zones/" + strings.Split(one["machineType"].(string), "/")[1]
				items[zone] = map[string][]any{"instances": append(items[zone]["instances"], one)}
			}
			answer(map[string]any{"items": items})
		case path == "/v1/services/6F81-5844-456A/skus":
			answer(map[string]any{"skus": []any{
				sku("Spot Preemptible C4A Arm Instance Core running in Netherlands", "europe-west4", 175_000_000, "h"),
				sku("Spot Preemptible C4A Arm Instance Ram running in Netherlands", "europe-west4", 1_000_000, "h"),
				sku("Hyperdisk Balanced Capacity in Netherlands", "europe-west4", 73_000_000, "GiBy.mo"),
				sku("External IP Charge on a Spot Preemptible VM", "global", 2_500_000, "h")}})
		case path == "/aggregated/machineTypes":
			answer(map[string]any{"items": map[string]any{"zones/europe-west4-a": map[string]any{"machineTypes": []any{
				map[string]any{"name": "c4a-standard-8", "guestCpus": 8, "memoryMb": 32768, "architecture": "ARM64"}}}}})
		case at < 0 || !strings.Contains(path, "/instances/"):
			http.NotFound(w, r)
		case r.Method == http.MethodGet:
			answer(listing[at])
		case refused[name]:
			http.Error(w, "{}", http.StatusForbidden)
		default:
			listing = slices.Delete(listing, at, at+1)
			answer(map[string]any{})
		}
	}))
	defer google.Close()
	t.Setenv("AK_GOOGLE_URL", google.URL)
	set := func(change func()) {
		held.Lock()
		defer held.Unlock()
		change()
	}
	rental := func(id, name, zone, kind, created string, hours int, address string) map[string]any {
		one := map[string]any{"id": id, "name": name, "labels": map[string]string{"ak": "rented"},
			"creationTimestamp": created, "machineType": "zones/" + zone + "/machineTypes/" + kind,
			"scheduling": map[string]any{"maxRunDuration": map[string]string{"seconds": strconv.Itoa(hours * 3600)}}}
		if address != "" {
			one["networkInterfaces"] = []any{map[string]any{"accessConfigs": []any{map[string]string{"natIP": address}}}}
		}
		return one
	}
	// a pass at a time and a config: whether Go carried it, its error, and what it asked of Google
	pass := func(at float64, config string) (bool, error, []string) {
		t.Helper()
		write("clock", strconv.FormatFloat(at, 'f', -1, 64))
		write("config.toml", config)
		held.Lock()
		start := len(asked)
		held.Unlock()
		carried, err := Watch("")
		held.Lock()
		defer held.Unlock()
		return carried, err, slices.Clone(asked[start:])
	}
	const (
		november, december = 1793491200.0, 1796083200.0 // 1 Nov and 1 Dec 2026, 00:00 UTC
		hour               = 3600.0
		renting            = "[google_cloud]\nactive = true\nmax_month = 50\n"
		off                = "[google_cloud]\nactive = false\nmax_month = 50\n"
		routes             = "Host *\n  Include ~/.ssh/config\n"
		listed             = "GET /aggregated/instances"
		priced             = "GET /v1/services/6F81-5844-456A/skus"
	)
	offers := func(at float64) string {
		zoned := `["europe-west4-a"], "projects/debian-cloud/global/images/family/debian-13-arm64", "hyperdisk-balanced"`
		return fmt.Sprintf(`{"at": %.1f, "offers": [["c4a-standard-8", "europe-west4", 8, 32768, 1.5, %[2]s],
			["n2d-standard-8", "europe-west4", 4.0, 32768, 0.75, %[2]s]]}`, at, zoned)
	}
	thirteen := rental("13", "acme-13", "us-central1-a", "n2d-standard-8", "2026-11-01T01:30:00Z", 6, "")

	// At 02:00: acme-11, listed before, from the last answer at the price it holds, dearer than its
	// type's; ak-aaa, on the meter by name, and the new acme-14 and acme-15 from their creation at
	// their type's; acme-13, a type not offered in its region, at the dearest offered. acme-12, gone,
	// is paid to its end; ak-bbb, on the meter by name and not listed, stays as it is. The two past
	// their end go back, a refusal said in Google's words. ak's ssh key is made, ssh-keygen's copy
	// of the hosts it knew forgotten, and an old route goes.
	write("state/google-cloud-offers.json", offers(november))
	write("state/google-cloud-ledger.json", `{"answered": 1793494800.0, "spent": 3.25, "machines": {
		"11": {"price": 1.75, "until": 1793505600.0}, "12": {"price": 1.0, "until": 1793496600.0},
		"ak-aaa": {"price": 0.5, "from": 1793494800.0, "until": 1793502000.0},
		"ak-bbb": {"price": 0.5, "from": 1793494800, "until": 1793509200}}}`)
	write("state/google-cloud-ssh-config", "Host acme-old\n  # until 1793509200\n  HostName \"192.0.2.1\"\n"+routes)
	write("secrets/google-cloud-known-hosts.old", "192.0.2.1 ssh-ed25519 AAAA\n")
	set(func() {
		listing = []map[string]any{
			rental("11", "acme-11", "europe-west4-a", "c4a-standard-8", "2026-10-31T16:00:00-07:00", 5, ""),
			rental("21", "ak-aaa", "europe-west4-a", "c4a-standard-8", "2026-11-01T01:10:00Z", 2, ""),
			rental("14", "acme-14", "europe-west4-a", "c4a-standard-8", "2026-11-01T00:00:00Z", 2, ""),
			rental("15", "acme-15", "europe-west4-b", "c4a-standard-8", "2026-11-01T01:00:00Z", 1, ""), thirteen}
		refused["acme-14"] = true
	})
	carried, err, got := pass(november+2*hour, renting)
	if !carried || err != nil || !slices.Equal(got, []string{listed, "GET acme-14", "DELETE acme-14", "GET acme-15", "DELETE acme-15"}) {
		t.Fatalf("carried %v, %v, asking %q", carried, err, got)
	}
	metered := `{
  "answered": 1793498400.0,
  "spent": 12.0,
  "machines": {
    "11": {
      "price": 1.75,
      "until": 1793505600.0
    },
    "21": {
      "price": 1.5,
      "until": 1793502600.0
    },
    "14": {
      "price": 1.5,
      "until": 1793498400.0
    },
    "15": {
      "price": 1.5,
      "until": 1793498400.0
    },
    "13": {
      "price": 1.5,
      "until": 1793518200.0
    },
    "ak-bbb": {
      "price": 0.5,
      "from": 1793494800,
      "until": 1793509200
    }
  }
}
`
	if got := read("state/google-cloud-ledger.json"); got != metered {
		t.Errorf("metered %s", got)
	}
	if got := read("state/google-cloud-late.json"); got != `[
  "acme-14 listed past its end, not given back: Google refused: Forbidden",
  "acme-15 listed past its end, given back"
]
` {
		t.Errorf("said %s", got)
	}
	if got := read("state/google-cloud-ssh-config"); got != routes {
		t.Errorf("routes %q", got)
	}
	if !gone("secrets/google-cloud-known-hosts.old") {
		t.Error("ssh-keygen's copy of the hosts it knew stayed")
	}
	if _, err := exec.LookPath("ssh-keygen"); err == nil && !strings.HasPrefix(read("secrets/google-cloud-ssh.pub"), "ssh-ed25519 ") {
		t.Error("no ssh key made")
	}

	// A need noted while ak may rent with work marked and the cap leaves money is Python's,
	// decided before anything is written, the need included.
	write("state/google-cloud-need", "4096 tests\n")
	if carried, err, got := pass(november+6*hour, renting); carried || err != nil || !slices.Equal(got, []string{listed}) {
		t.Errorf("a need to rent for: carried %v, %v, asking %q", carried, err, got)
	}
	if read("state/google-cloud-need") != "4096 tests\n" || read("state/google-cloud-ledger.json") != metered {
		t.Error("a pass left to Python wrote")
	}

	// At 06:00 acme-11 and ak-aaa, gone, are paid to their ends, ak-bbb past its end is paid whole,
	// and acme-13 goes back past the cap, which leaves nothing to rent for the need with: it is
	// taken, and Google asked nothing for it.
	set(func() { listing = []map[string]any{thirteen} })
	carried, err, got = pass(november+6*hour, strings.Replace(renting, "50", "20", 1))
	if !carried || err != nil || !slices.Equal(got, []string{listed, "GET acme-13", "DELETE acme-13"}) {
		t.Errorf("past the cap: carried %v, %v, asking %q", carried, err, got)
	}
	if !gone("state/google-cloud-need") || read("state/google-cloud-need.taken") != "4096 tests\n" {
		t.Error("the need past the cap was not taken")
	}
	if got := read("state/google-cloud-ledger.json"); got != `{
  "answered": 1793512800.0,
  "spent": 25.25,
  "machines": {
    "13": {
      "price": 1.5,
      "until": 1793518200.0
    }
  }
}
` {
		t.Errorf("metered %s", got)
	}
	if got := read("state/google-cloud-late.json"); got != `[
  "acme-13 listed past the cap, given back",
  "rents nothing: \u20ac27.50 of \u20ac20.00 spent this month or held to the machines' ends leaves less than 10 minutes of c4a-standard-8"
]
` {
		t.Errorf("said %s", got)
	}

	// December counts acme-31's own half hour alone, and offers kept a month are listed anew.
	set(func() {
		listing = []map[string]any{rental("31", "acme-31", "europe-west4-a", "c4a-standard-8", "2026-11-30T23:00:00Z", 6, "")}
	})
	carried, err, got = pass(december+hour/2, renting)
	if !carried || err != nil || !slices.Equal(got, []string{listed, priced, "GET /aggregated/machineTypes"}) {
		t.Errorf("a new month: carried %v, %v, asking %q", carried, err, got)
	}
	if got := read("state/google-cloud-ledger.json"); got != `{
  "answered": 1796085000.0,
  "spent": 0.75,
  "machines": {
    "31": {
      "price": 1.5,
      "until": 1796101200.0
    }
  }
}
` {
		t.Errorf("metered %s", got)
	}
	if got := read("state/google-cloud-late.json"); got != "[]\n" {
		t.Errorf("said %s", got)
	}
	if at, kept := Kept(); at != december+hour/2 || len(kept) != 1 || !slices.Equal(kept[0].Zones, []string{"europe-west4-a"}) {
		t.Errorf("kept at %v: %+v", at, kept)
	}

	// A meter that cannot be read is past the cap and kept as it is, a refusal still said; offers
	// kept without zones are listed anew.
	set(func() { refused["acme-31"] = true })
	for _, text := range []string{"{", `{"answered": 1, "spent": NaN, "machines": {}}`} {
		write("state/google-cloud-ledger.json", text)
		write("state/google-cloud-offers.json", `{"at": 1796085180.0, "offers": [["c4a-standard-8", "europe-west4", 8, 32768, 1.5]]}`)
		carried, err, got := pass(december+hour/2+180, renting)
		if !carried || err != nil || !slices.Contains(got, priced) {
			t.Errorf("%s: carried %v, %v, asking %q", text, carried, err, got)
		}
		if got := read("state/google-cloud-ledger.json"); got != text {
			t.Errorf("%s kept as %s", text, got)
		}
		if got := read("state/google-cloud-late.json"); got != "[\n  \"acme-31 listed past the cap, not given back: Google refused: Forbidden\"\n]\n" {
			t.Errorf("%s: said %s", text, got)
		}
	}

	// While ak may not rent a need noted is taken, a machine goes back with no price kept, and no
	// offers are listed.
	set(func() { delete(refused, "acme-31") })
	os.Remove(filepath.Join(ak, "state/google-cloud-offers.json"))
	write("state/google-cloud-need", "4096 tests\n")
	carried, err, got = pass(december+hour/2+360, off)
	if !carried || err != nil || !slices.Equal(got, []string{listed, "GET acme-31", "DELETE acme-31"}) {
		t.Errorf("not renting: carried %v, %v, asking %q", carried, err, got)
	}
	if got := read("state/google-cloud-late.json"); got != "[\n  \"acme-31 listed with no price kept, given back\"\n]\n" {
		t.Errorf("not renting: said %s", got)
	}
	if !gone("state/google-cloud-need") || read("state/google-cloud-need.taken") != "4096 tests\n" {
		t.Error("the need was not taken")
	}

	// With no work marked a machine still starting goes back, metered from nothing before.
	os.Remove(filepath.Join(ak, "state/google-cloud-ledger.json"))
	write("state/google-cloud-offers.json", offers(december))
	set(func() {
		listing = []map[string]any{rental("32", "acme-32", "europe-west4-a", "c4a-standard-8", "2026-12-01T00:30:00Z", 6, "")}
	})
	carried, err, got = pass(december+hour, renting+"work = []\n")
	if !carried || err != nil || !slices.Equal(got, []string{listed, "GET acme-32", "DELETE acme-32"}) {
		t.Errorf("no work marked: carried %v, %v, asking %q", carried, err, got)
	}
	if got := read("state/google-cloud-late.json"); got != "[\n  \"acme-32 listed no work marked, given back\"\n]\n" {
		t.Errorf("no work marked: said %s", got)
	}
	if got := read("state/google-cloud-ledger.json"); !strings.HasPrefix(got, "{\n  \"answered\": 1796086800.0,\n  \"spent\": 0.75,\n") {
		t.Errorf("metered from nothing: %s", got)
	}

	// A listing Google refuses is the pass's error, nothing written; with neither renting nor a
	// key, Google is asked nothing.
	set(func() { refusing = true })
	said := read("state/google-cloud-late.json")
	if carried, err, _ := pass(december+2*hour, renting); !carried || fmt.Sprint(err) != "Google refused: Forbidden" ||
		read("state/google-cloud-late.json") != said {
		t.Errorf("a listing refused: carried %v, %v", carried, err)
	}
	os.Remove(filepath.Join(ak, "secrets/google-cloud.json"))
	if carried, err, got := pass(december+2*hour, off); !carried || err != nil || len(got) != 0 || read("state/google-cloud-late.json") != said {
		t.Errorf("no key: carried %v, %v, asking %q", carried, err, got)
	}
}
