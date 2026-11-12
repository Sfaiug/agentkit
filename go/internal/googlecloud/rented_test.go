package googlecloud

import (
	"crypto/rand"
	"crypto/rsa"
	"crypto/x509"
	"encoding/base64"
	"encoding/json"
	"encoding/pem"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/http/httptest"
	"net/url"
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

// What ak rents is listed whole and given back only while Google still names it ak's; a refusal
// carries Google's codes, and a Google that does not answer is asked nothing more; offers say
// where and on what a machine boots, kept as Python keeps them, on the package's clock.
func TestGoogleListsWhatAkRentsAndGivesOneBack(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	write := func(name, text string) string {
		t.Helper()
		path := filepath.Join(home, ".agentkit", name)
		if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(text), 0o600); err != nil {
			t.Fatal(err)
		}
		return path
	}
	private, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatal(err)
	}
	der, _ := x509.MarshalPKCS8PrivateKey(private)
	key, _ := json.Marshal(map[string]string{"project_id": "acme-build", "client_email": "ak@acme-build.example",
		"private_key": string(pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: der}))})
	write("secrets/google-cloud.json", string(key))
	t.Setenv("AK_GOOGLE_CLOCK", write("clock", " 1715798400.25\n"))
	t.Cleanup(func() { unanswered = nil })

	// Google: a token for any JWT, else each answer by method and path, Compute Engine's under the
	// project, and a 404 for any other
	type reply struct {
		status int // none: no such answer
		body   string
		short  int // bytes promised that never come
	}
	const project = "/compute/v1/projects/acme-build"
	var held sync.Mutex
	answers := map[string]reply{}
	var asked []string // each method and path, and what was sent: a JWT's iat
	google := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		held.Lock()
		defer held.Unlock()
		sent, _ := io.ReadAll(r.Body)
		request := r.Method + " " + strings.TrimPrefix(r.URL.RequestURI(), project)
		if r.URL.Path == "/token" {
			form, _ := url.ParseQuery(string(sent))
			_, claims, _ := strings.Cut(form.Get("assertion"), ".")
			claims, _, _ = strings.Cut(claims, ".")
			decoded, _ := base64.RawURLEncoding.DecodeString(claims)
			var jwt struct{ Iat int64 }
			json.Unmarshal(decoded, &jwt)
			asked = append(asked, fmt.Sprint(request, " ", jwt.Iat))
			fmt.Fprint(w, `{"access_token": "ya29.acme"}`)
			return
		}
		if len(sent) > 0 {
			request += " " + r.Header.Get("Content-Type") + " " + string(sent)
		}
		asked = append(asked, request)
		answer, ok := answers[r.Method+" "+strings.TrimPrefix(r.URL.RequestURI(), project)]
		if !ok {
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Content-Length", strconv.Itoa(len(answer.body)+answer.short))
		w.WriteHeader(answer.status)
		io.WriteString(w, answer.body)
	}))
	defer google.Close()
	t.Setenv("AK_GOOGLE_URL", google.URL)
	answer := func(request string, said reply) {
		held.Lock()
		defer held.Unlock()
		answers[request] = said
		if said.status == 0 {
			delete(answers, request)
		}
	}
	since := func(start int) []string {
		held.Lock()
		defer held.Unlock()
		return slices.Clone(asked[start:])
	}

	// Two pages: someone else's machine and a zone of none, then ak's.
	theirs := `{"id": "7", "name": "acme-own", "labels": {"team": "acme"},
		"machineType": "zones/europe-west4-a/machineTypes/n2d-standard-8"}`
	ours := `{"id": "1001", "name": "acme-1", "labels": {"ak": "rented"},
		"creationTimestamp": "2024-05-15T11:00:00.500-07:00",
		"machineType": "https://www.googleapis.com/compute/v1/projects/acme-build/zones/europe-west4-b/machineTypes/c4a-standard-8",
		"scheduling": {"maxRunDuration": {"seconds": "21600"}},
		"networkInterfaces": [{"name": "nic0"}, {"accessConfigs": [{"natIP": "203.0.113.7"}, {"natIP": "203.0.113.8"}]}]}`
	answer("GET /aggregated/instances?", reply{200, `{"items": {"zones/europe-west4-a": {"instances": [` + theirs +
		`]}, "zones/us-central1-a": {"warning": {"code": "NO_RESULTS_ON_PAGE"}}}, "nextPageToken": "2"}`, 0})
	answer("GET /aggregated/instances?pageToken=2", reply{200, `{"items": {"zones/europe-west4-b": {"instances": [` + ours + `]}}}`, 0})
	created := float64(time.Date(2024, 5, 15, 18, 0, 0, 5e8, time.UTC).UnixMicro()) / 1e6
	machine := Machine{"1001", "acme-1", "europe-west4-b", "c4a-standard-8", created, created + 21600, "203.0.113.7"}
	listed, err := Rented()
	if err != nil || !reflect.DeepEqual(listed, []Machine{machine}) {
		t.Fatalf("listed %+v, %v", listed, err)
	}
	// no partial answer asked for
	token := "POST /token 1715798400" // the clock's, a fraction and spaces aside
	if got := since(0); !slices.Equal(got, []string{token, "GET /aggregated/instances?", "GET /aggregated/instances?pageToken=2"}) {
		t.Errorf("asked %q", got)
	}
	answer("GET /aggregated/instances?pageToken=2", reply{200, `{"items": {}, "unreachables": ["zones/us-central1-c"]}`, 0})
	if listed, err := Rented(); listed != nil || fmt.Sprint(err) != "asking Google failed: zones/us-central1-c unreachable" {
		t.Errorf("a zone missed: %+v, %v", listed, err)
	}

	// Asked again, the machine goes only while it is that one and ak's; a 404 is gone already.
	path := "/zones/europe-west4-b/instances/acme-1"
	deleted := reply{200, `{"name": "operation-1"}`, 0}
	for _, each := range []struct {
		found, deleting reply
		asked           []string
	}{
		{reply{200, ours, 0}, deleted, []string{token, "GET " + path, "DELETE " + path}},
		{reply{200, ours, 0}, reply{}, []string{token, "GET " + path, "DELETE " + path}},
		{reply{200, strings.Replace(ours, `"1001"`, `"1002"`, 1), 0}, deleted, []string{token, "GET " + path}},
		{reply{200, strings.Replace(ours, `"rented"`, `"kept"`, 1), 0}, deleted, []string{token, "GET " + path}},
		{reply{}, deleted, []string{token, "GET " + path}},
	} {
		answer("GET "+path, each.found)
		answer("DELETE "+path, each.deleting)
		start := len(since(0))
		if err := GiveBack(machine); err != nil || !slices.Equal(since(start), each.asked) {
			t.Errorf("found %+v, deleting %+v: %v, asked %q", each.found, each.deleting, err, since(start))
		}
	}

	// A refusal's codes are its body's, whole, and one of 500 or more has none.
	refusing := `{"error": {"code": 403, "errors": [{"reason": "quotaExceeded"}, {"code": "QUOTA_EXCEEDED", "reason": "x"},
		{"reason": "quotaExceeded"}, {"message": "acme"}]}}`
	for _, each := range []struct {
		status, short int
		said          string
		codes         []string
	}{
		{403, 0, "Google refused: Forbidden", []string{"QUOTA_EXCEEDED", "quotaExceeded"}},
		{403, 1, "Google refused: Forbidden", nil},
		{503, 0, "Google refused: Service Unavailable", nil},
	} {
		answer("GET "+path, reply{each.status, refusing, each.short})
		err := GiveBack(machine)
		var refused *refusal
		if !errors.As(err, &refused) || err.Error() != each.said || !slices.Equal(refused.codes, each.codes) {
			t.Errorf("%d, %d short: %v, %+v", each.status, each.short, err, refused)
		}
	}
	answer("GET /aggregated/instances?", reply{})
	if _, err := Rented(); fmt.Sprint(err) != "Google refused: Not Found" { // a 404 where nobody said gone
		t.Errorf("listing refused: %v", err)
	}

	// JSON goes with any method to Google's APIs, the token alone a form.
	start := len(since(0))
	var made struct{ Status string }
	answer("POST /zones/europe-west4-b/instances", reply{200, `{"status": "DONE"}`, 0})
	if err := call(http.MethodPost, google.URL+project+"/zones/europe-west4-b/instances", "ya29.acme",
		map[string]string{"name": "acme-2"}, &made); err != nil || made.Status != "DONE" ||
		!slices.Equal(since(start), []string{`POST /zones/europe-west4-b/instances application/json {"name":"acme-2"}`}) {
		t.Errorf("sent JSON: %v, %+v, asked %q", err, made, since(start))
	}

	// Offers carry their region's zones, image and boot disk, and are kept as Python keeps them,
	// at the clock's time read anew.
	write("clock", "1715802000.5")
	sku := func(description, region string, nanos int, unit string) string {
		return fmt.Sprintf(`{"description": %q, "serviceRegions": [%q], "pricingInfo": [{"pricingExpression":
			{"usageUnit": %q, "tieredRates": [{"unitPrice": {"units": "0", "nanos": %d}}]}}]}`, description, region, unit, nanos)
	}
	answer("GET /v1/services/6F81-5844-456A/skus?currencyCode=EUR&pageSize=5000", reply{200, `{"skus": [` + strings.Join([]string{
		sku("Spot Preemptible C4A Arm Instance Core running in Netherlands", "europe-west4", 10_000_000, "h"),
		sku("Spot Preemptible C4A Arm Instance Ram running in Netherlands", "europe-west4", 1_000_000, "h"),
		sku("Spot Preemptible N2D AMD Instance Core running in Netherlands", "europe-west4", 6_000_000, "h"),
		sku("Spot Preemptible N2D AMD Instance Ram running in Netherlands", "europe-west4", 800_000, "h"),
		sku("Hyperdisk Balanced Capacity in Netherlands", "europe-west4", 73_000_000, "GiBy.mo"),
		sku("Balanced PD Capacity in Netherlands", "europe-west4", 109_500_000, "GiBy.mo"),
		sku("External IP Charge on a Spot Preemptible VM", "global", 2_500_000, "h")}, ", ") + `]}`, 0})
	arm := `{"name": "c4a-standard-8", "guestCpus": 8, "memoryMb": 32768, "architecture": "ARM64"}`
	x86 := `{"name": "n2d-standard-8", "guestCpus": 8, "memoryMb": 32768, "architecture": "X86_64"}`
	answer("GET /aggregated/machineTypes?returnPartialSuccess=true", reply{200, `{"items": {"zones/europe-west4-b":
		{"machineTypes": [` + arm + `]}, "zones/europe-west4-a": {"machineTypes": [` + arm + ", " + x86 + `]}}}`, 0})
	start = len(since(0))
	offered, err := Offers()
	var got []string
	for _, o := range offered {
		got = append(got, fmt.Sprintf("%s in %s: %g cores, %g vCPUs, %v, %s, %s", o.Name, o.Region, o.Cores, o.CPUs(), o.Zones, o.Image, o.Disk))
	}
	if err != nil || !slices.Equal(got, []string{
		"c4a-standard-8 in europe-west4: 8 cores, 8 vCPUs, [europe-west4-a europe-west4-b], " +
			"projects/debian-cloud/global/images/family/debian-13-arm64, hyperdisk-balanced",
		"n2d-standard-8 in europe-west4: 4 cores, 8 vCPUs, [europe-west4-a], projects/debian-cloud/global/images/family/debian-13, pd-balanced",
	}) {
		t.Errorf("offered %q, %v", got, err)
	}
	if got := since(start); len(got) == 0 || got[0] != "POST /token 1715802000" {
		t.Errorf("asked %q", got)
	}
	if err := Keep(offered); err != nil {
		t.Fatal(err)
	}
	if at, kept := Kept(); at != 1715802000.5 || !reflect.DeepEqual(kept, offered) {
		t.Errorf("kept at %v: %+v", at, kept)
	}
	write("clock", "1715805600.5\n")
	if err := Keep([]Offer{{"c4a-standard-8", "europe-west4", 8, 32768, 0.064, []string{"europe-west4-a"},
		"projects/debian-cloud/global/images/family/debian-13-arm64", "hyperdisk-balanced"}}); err != nil {
		t.Fatal(err)
	}
	python := `{
  "at": 1715805600.5,
  "offers": [
    [
      "c4a-standard-8",
      "europe-west4",
      8,
      32768,
      0.064,
      [
        "europe-west4-a"
      ],
      "projects/debian-cloud/global/images/family/debian-13-arm64",
      "hyperdisk-balanced"
    ]
  ]
}
`
	if text, _ := os.ReadFile(filepath.Join(home, ".agentkit/state/google-cloud-offers.json")); string(text) != python {
		t.Errorf("kept as %s", text)
	}
	// kept before ak rented: an offer of five fields, two vCPUs a core
	write("state/google-cloud-offers.json", `{"at": 1715798400.0, "offers": [["n2d-standard-8", "europe-west4", 4.0, 32768, 0.1]]}`)
	if at, kept := Kept(); at != 1715798400 || !reflect.DeepEqual(kept, []Offer{{Name: "n2d-standard-8",
		Region: "europe-west4", Cores: 4, MemoryMB: 32768, Hourly: 0.1}}) || kept[0].CPUs() != 8 {
		t.Errorf("five fields kept at %v: %+v", at, kept)
	}
	write("state/google-cloud-offers.json", `{"at": 1715798400.0, "offers": [["n2d-standard-8", "europe-west4", 4.0, 32768]]}`)
	if at, kept := Kept(); at != 0 || kept != nil {
		t.Errorf("four fields kept at %v: %+v", at, kept)
	}
	write("state/google-cloud-offers.json", `{"at": null, "offers": [["n2d-standard-8", "europe-west4", 4.0, 32768, 0.1]]}`)
	if at, kept := Kept(); possible(at) || len(kept) != 1 {
		t.Errorf("kept at null as %v: %+v", at, kept)
	}
	write("state/google-cloud-offers.json", `{"offers": [["n2d-standard-8", "europe-west4", 4.0, 32768, 0.1]]}`)
	if at, kept := Kept(); at != 0 || kept != nil {
		t.Errorf("kept with no at as %v: %+v", at, kept)
	}

	// A reply cut short, in its body or its header, fails that call alone; once Google does not
	// answer, with no connection, a certificate refused, one closed before any reply or a reply
	// stalled past a call's time, every later call fails in its words, asking nothing.
	answer("GET "+path, reply{200, ours, 1})
	if err := GiveBack(machine); fmt.Sprint(err) != "asking Google failed: unexpected EOF" {
		t.Errorf("cut short: %v", err)
	}
	hanging := func(said string) string { // a Google saying said and hanging up
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			conn, _, _ := w.(http.Hijacker).Hijack()
			io.WriteString(conn, said)
			conn.Close()
		}))
		t.Cleanup(server.Close)
		return server.URL
	}
	t.Setenv("AK_GOOGLE_URL", hanging("HTTP/1.1 200 OK\r\nContent-Len"))
	if _, err := Rented(); !strings.HasPrefix(fmt.Sprint(err), "asking Google failed: ") {
		t.Errorf("header cut short: %v", err)
	}
	t.Setenv("AK_GOOGLE_URL", google.URL)
	answer("GET "+path, reply{200, ours, 0})
	start = len(since(0))
	if err := GiveBack(machine); err != nil || !slices.Equal(since(start), []string{"POST /token 1715805600", "GET " + path, "DELETE " + path}) {
		t.Errorf("after one cut short: %v, asked %q", err, since(start))
	}
	was := client.Timeout
	t.Cleanup(func() { client.Timeout = was })
	client.Timeout = 100 * time.Millisecond
	closed := httptest.NewServer(http.NotFoundHandler())
	closed.Close()
	stalled := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Length", "100")
		io.WriteString(w, "{")
		w.(http.Flusher).Flush()
		<-r.Context().Done()
	}))
	defer stalled.Close()
	untrusted := httptest.NewUnstartedServer(http.NotFoundHandler())
	untrusted.Config.ErrorLog = log.New(io.Discard, "", 0) // its refused handshake
	untrusted.StartTLS()
	defer untrusted.Close()
	for _, silent := range []string{closed.URL, untrusted.URL, hanging(""), stalled.URL} {
		unanswered = nil
		t.Setenv("AK_GOOGLE_URL", silent)
		_, err := Rented()
		said := fmt.Sprint(err)
		t.Setenv("AK_GOOGLE_URL", google.URL)
		start := len(since(0))
		if _, err := Rented(); !strings.HasPrefix(said, "asking Google failed: ") || fmt.Sprint(err) != said || len(since(start)) != 0 {
			t.Errorf("after %s answered none (%s): %v, asked %q", silent, said, err, since(start))
		}
	}
}
