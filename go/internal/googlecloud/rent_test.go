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
	"strconv"
	"strings"
	"sync"
	"testing"

	"agentkit/internal/run"
)

// A need noted rents the offer cheapest a core that fits, in a zone without ak's machines first,
// living what the cap leaves, asked for as Python asks; a refusal of stock moves on to the next
// zone, another refusal ends the rent, and a create Google does not answer stays on the meter by
// name. Nothing is rented while one comes up, while ak may not rent, or where the cap leaves less
// than ten minutes, each line said as Python says it. Where Google lists a quota limit in a region
// offered the pass is Python's, nothing written; a limit read Google does not answer lists none.
func TestARentTakesTheCheapestCoreForWhatTheCapLeaves(t *testing.T) {
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
	// one type too small and one short of memory, cheaper a core than the two that fit
	zoned := `["europe-west4-a", "europe-west4-b"], "projects/debian-cloud/global/images/family/debian-13-arm64", "hyperdisk-balanced"`
	write("state/google-cloud-offers.json", fmt.Sprintf(`{"at": 1793577420.0, "offers": [
		["c4a-standard-4", "europe-west4", 4, 16384, 0.4, %[1]s], ["c4a-small-8", "europe-west4", 8, 3072, 1.0, %[1]s],
		["c4a-standard-8", "europe-west4", 8, 32768, 2.5, %[1]s], ["c4a-highcpu-8", "europe-west4", 8, 16384, 2.0, %[1]s]]}`, zoned))
	// €2 spent by midnight, and acme-1 in europe-west4-a holds €2 more to its end at 02:00
	write("state/google-cloud-ledger.json", `{"answered": 1793575800.0, "spent": 1.5, "machines": {
		"1": {"price": 1.0, "until": 1793584800.0}}}`)

	// Google: a token for any JWT, acme-1 listed, c4a-highcpu-8 offered in europe-west4-a unless the
	// listing is not answered, no quota limit unless europe-west4's CPUS is listed, or the read of
	// them not answered; each create's body kept, answered by the next of answers, else made, and
	// operation-1 done.
	const project = "/compute/v1/projects/acme-build"
	var held sync.Mutex
	var made []map[string]any
	var answers []func(http.ResponseWriter)
	limit, catalogue := "", ""
	reply := func(code int, body string) func(http.ResponseWriter) {
		return func(w http.ResponseWriter) {
			w.WriteHeader(code)
			io.WriteString(w, body)
		}
	}
	silent := func(w http.ResponseWriter) {
		conn, _, _ := w.(http.Hijacker).Hijack()
		conn.Close()
	}
	google := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		held.Lock()
		defer held.Unlock()
		path := strings.TrimPrefix(r.URL.Path, project)
		switch {
		case path == "/token":
			io.WriteString(w, `{"access_token": "ya29.acme"}`)
		case path == "/aggregated/instances":
			io.WriteString(w, `{"items": {"zones/europe-west4-a": {"instances": [{"id": "1", "name": "acme-1",
				"labels": {"ak": "rented"}, "creationTimestamp": "2026-11-01T23:00:00Z",
				"machineType": "zones/europe-west4-a/machineTypes/c4a-small-8", "scheduling": {"maxRunDuration": {"seconds": "10800"}}}]}}}`)
		case strings.HasSuffix(path, "/compute.googleapis.com/cpus_per_vm_family") && limit == "silent":
			silent(w)
		case strings.HasSuffix(path, "/compute.googleapis.com/cpus_per_vm_family"):
			io.WriteString(w, `{"consumerQuotaLimits": [{"quotaBuckets": [{"dimensions": {"region": "europe-west4"}}]}]}`)
		case path == "/regions/europe-west4" && limit == "listed":
			io.WriteString(w, `{"quotas": [{"metric": "CPUS", "limit": 24.0}]}`)
		case strings.HasPrefix(path, "/regions/"):
			io.WriteString(w, `{"quotas": [{"metric": "INSTANCES", "limit": 24.0}]}`)
		case path == "/v1/services/6F81-5844-456A/skus" && catalogue == "silent":
			silent(w)
		case path == "/v1/services/6F81-5844-456A/skus":
			sku := func(description, region string, nanos int, unit string) string {
				return fmt.Sprintf(`{"description": %q, "serviceRegions": [%q], "pricingInfo": [{"pricingExpression":
					{"usageUnit": %q, "tieredRates": [{"unitPrice": {"units": "0", "nanos": %d}}]}}]}`, description, region, unit, nanos)
			}
			io.WriteString(w, `{"skus": [`+sku("Spot Preemptible C4A Arm Instance Core running in Netherlands", "europe-west4", 175_000_000, "h")+", "+
				sku("Spot Preemptible C4A Arm Instance Ram running in Netherlands", "europe-west4", 1_000_000, "h")+", "+
				sku("Hyperdisk Balanced Capacity in Netherlands", "europe-west4", 73_000_000, "GiBy.mo")+", "+
				sku("External IP Charge on a Spot Preemptible VM", "global", 2_500_000, "h")+"]}")
		case path == "/aggregated/machineTypes":
			io.WriteString(w, `{"items": {"zones/europe-west4-a": {"machineTypes": [
				{"name": "c4a-highcpu-8", "guestCpus": 8, "memoryMb": 16384, "architecture": "ARM64"}]}}}`)
		case path == "":
			io.WriteString(w, `{"quotas": []}`)
		case r.Method == http.MethodPost && strings.HasSuffix(path, "/instances"):
			var body map[string]any
			json.NewDecoder(r.Body).Decode(&body)
			made = append(made, body)
			if len(answers) == 0 {
				io.WriteString(w, `{"status": "DONE"}`)
				return
			}
			answers[0](w)
			answers = answers[1:]
		case path == "/zones/europe-west4-a/operations/operation-1":
			io.WriteString(w, `{"status": "DONE"}`)
		default:
			http.NotFound(w, r)
		}
	}))
	defer google.Close()
	t.Setenv("AK_GOOGLE_URL", google.URL)
	set := func(change func()) {
		held.Lock()
		defer held.Unlock()
		change()
	}
	// a pass, each its own tick, at a time, with a cap and a need noted: whether Go carried it, its
	// error, and the creates it asked for
	pass := func(at float64, config, need string) (bool, error, []map[string]any) {
		t.Helper()
		write("clock", strconv.FormatFloat(at, 'f', -1, 64))
		write("config.toml", config)
		write("state/google-cloud-need", need)
		unanswered = nil
		held.Lock()
		start := len(made)
		held.Unlock()
		carried, err := Watch("")
		held.Lock()
		defer held.Unlock()
		return carried, err, made[start:]
	}
	renting := func(cap string) string { return "[google_cloud]\nactive = true\nmax_month = " + cap + "\n" }
	said := func() []string {
		var lines []string
		json.Unmarshal([]byte(read("state/google-cloud-late.json")), &lines)
		return lines
	}
	where := func(creates []map[string]any) []string {
		var zones []string
		for _, one := range creates {
			zones = append(zones, fmt.Sprint(one["machineType"]))
		}
		return zones
	}
	meter := func() *run.Object {
		ledger, _ := run.ReadJSON(meterPath())
		return ledger.Dict("machines")
	}

	// At midnight €10 leaves €6: c4a-highcpu-8 for 3 hours, refused for stock in europe-west4-b,
	// where ak has none, then made in europe-west4-a once Google's operation is done; asked for as
	// Python asks, on the meter by name.
	set(func() {
		answers = []func(http.ResponseWriter){
			reply(200, `{"status": "DONE", "error": {"errors": [{"code": "ZONE_RESOURCE_POOL_EXHAUSTED"}]}}`),
			reply(200, `{"status": "RUNNING", "name": "operation-1"}`)}
	})
	carried, err, creates := pass(midnight, renting("10"), "456 tests\n")
	if !carried || err != nil || !reflect.DeepEqual(where(creates), []string{"zones/europe-west4-b/machineTypes/c4a-highcpu-8",
		"zones/europe-west4-a/machineTypes/c4a-highcpu-8"}) {
		t.Fatalf("carried %v, %v, creating %q", carried, err, where(creates))
	}
	name := fmt.Sprint(creates[1]["name"])
	var python map[string]any
	json.Unmarshal([]byte(`{"name": "`+name+`", "machineType": "zones/europe-west4-a/machineTypes/c4a-highcpu-8", "labels": {"ak": "rented"}, "scheduling": {"provisioningModel": "SPOT", "instanceTerminationAction": "DELETE", "maxRunDuration": {"seconds": "10800"}, "automaticRestart": false, "onHostMaintenance": "TERMINATE"}, "disks": [{"boot": true, "autoDelete": true, "initializeParams": {"sourceImage": "projects/debian-cloud/global/images/family/debian-13-arm64", "diskSizeGb": "20", "diskType": "zones/europe-west4-a/diskTypes/hyperdisk-balanced"}}], "networkInterfaces": [{"accessConfigs": [{"type": "ONE_TO_ONE_NAT"}]}], "metadata": {"items": [{"key": "block-project-ssh-keys", "value": "true"}, {"key": "startup-script", "value": "#!/bin/bash\nset -e\nuseradd -m -s /bin/bash ak\nmkdir -p /var/lib/docker ~ak/.agentkit-helper ~ak/.ssh\nmount -t tmpfs -o size=70% tmpfs /var/lib/docker\nmount -t tmpfs -o size=70% tmpfs ~ak/.agentkit-helper\necho 'ssh-ed25519 AAAAacme ak' >~ak/.ssh/authorized_keys\nchown -R ak: ~ak\napt-get update -q && DEBIAN_FRONTEND=noninteractive apt-get install -qy docker.io docker-cli git jq\nusermod -aG docker ak\nprintf 'MaxStartups 500:30:1000\\nPerSourcePenalties no\\n' >/etc/ssh/sshd_config.d/ak.conf\nsystemctl reload ssh\ntouch /run/ak-ready\n"}]}}`), &python)
	if !strings.HasPrefix(name, "ak-") || len(name) != 15 || !reflect.DeepEqual(creates[1], python) {
		t.Errorf("asked for %v", creates[1])
	}
	if got := said(); !reflect.DeepEqual(got, []string{name + " rented: c4a-highcpu-8 in europe-west4-a"}) {
		t.Errorf("said %q", got)
	}
	if got := read("state/google-cloud-ledger.json"); got != `{
  "answered": 1793577600.0,
  "spent": 2.0,
  "machines": {
    "1": {
      "price": 1.0,
      "until": 1793584800.0
    },
    "`+name+`": {
      "price": 2.0,
      "from": 1793577600.0,
      "until": 1793588400.0
    }
  }
}
` {
		t.Errorf("metered %s", got)
	}

	// Nothing is rented while that machine comes up, nor while ak may not rent; each need is taken.
	for n, config := range []string{renting("10"), "[google_cloud]\nactive = false\nmax_month = 10\n"} {
		carried, err, creates := pass(midnight+180*float64(n+1), config, "456 tests\n")
		if !carried || err != nil || len(creates) > 0 || len(said()) > 0 || read("state/google-cloud-need") != "" {
			t.Errorf("%q: carried %v, %v, creating %q, said %q", config, carried, err, where(creates), said())
		}
	}

	// At 00:10, €10.25 leaves €0.25 past what each machine holds to its end: less than ten minutes
	// of either type.
	carried, err, creates = pass(midnight+600, renting("10.25"), "456 tests\n")
	if !carried || err != nil || len(creates) > 0 || !reflect.DeepEqual(said(), []string{"rents nothing: €10.00 of €10.25 spent " +
		"this month or held to the machines' ends leaves less than 10 minutes of c4a-standard-8"}) {
		t.Errorf("capped: carried %v, %v, creating %q, said %q", carried, err, where(creates), said())
	}

	// A create Google does not answer stays on the meter by name.
	set(func() { answers = []func(http.ResponseWriter){silent} })
	carried, err, creates = pass(midnight+780, renting("30"), "456 tests\n")
	if !carried || err != nil || len(creates) != 1 {
		t.Fatalf("unanswered: carried %v, %v, creating %q", carried, err, where(creates))
	}
	name = fmt.Sprint(creates[0]["name"])
	if from, _ := meter().Dict(name).Num("from"); from != midnight+780 || len(said()) != 1 ||
		!strings.HasPrefix(said()[0], name+" asked for in europe-west4-b, kept on the meter: asking Google failed: ") {
		t.Errorf("unanswered: said %q, metered from %v", said(), from)
	}

	// A limit read Google does not answer lists none and leaves the rent its calls; a refusal of
	// no quota or stock ends the rent, and what Google made none of leaves the meter.
	set(func() {
		limit, answers = "silent", []func(http.ResponseWriter){reply(400, `{"error": {"errors": [{"reason": "invalid"}]}}`)}
	})
	carried, err, creates = pass(midnight+1380, renting("50"), "456 tests\n")
	if !carried || err != nil || len(creates) != 1 || meter().Has(fmt.Sprint(creates[0]["name"])) ||
		!reflect.DeepEqual(said(), []string{"c4a-highcpu-8 in europe-west4-b refused: invalid"}) {
		t.Errorf("refused: carried %v, %v, creating %q, said %q", carried, err, where(creates), said())
	}

	// A need nothing offered fits says so.
	set(func() { limit = "" })
	carried, err, creates = pass(midnight+1560, renting("50"), "8192 tests\n")
	if !carried || err != nil || len(creates) > 0 || !reflect.DeepEqual(said(), []string{"nothing offered with 8192 MiB a vCPU"}) {
		t.Errorf("nothing fits: carried %v, %v, creating %q, said %q", carried, err, where(creates), said())
	}

	// Where Google lists a quota limit in a region offered the pass is Python's, nothing written, the
	// need included, whatever the cap leaves: offers kept a day are listed anew first, and where
	// Google does not answer that listing, those kept are offered.
	ledger, late := read("state/google-cloud-ledger.json"), read("state/google-cloud-late.json")
	for _, kept := range []struct{ catalogue, region string }{{"", "us-central1"}, {"silent", "europe-west4"}} {
		set(func() { limit, catalogue = "listed", kept.catalogue })
		offers := fmt.Sprintf(`{"at": 1793491200.0, "offers": [["c4a-highcpu-8", %[1]q, 8, 16384, 2.0, ["%[1]s-a"],
			"projects/debian-cloud/global/images/family/debian-13-arm64", "hyperdisk-balanced"]]}`, kept.region)
		write("state/google-cloud-offers.json", offers)
		carried, err, creates = pass(midnight+1740, renting("1"), "456 tests\n")
		if carried || err != nil || len(creates) > 0 || read("state/google-cloud-need") != "456 tests\n" ||
			read("state/google-cloud-ledger.json") != ledger || read("state/google-cloud-late.json") != late ||
			read("state/google-cloud-offers.json") != offers {
			t.Errorf("%+v: carried %v, %v, creating %q", kept, carried, err, where(creates))
		}
	}
}
