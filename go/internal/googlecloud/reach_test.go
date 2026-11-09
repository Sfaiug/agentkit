//go:build unix

package googlecloud

import (
	"crypto/rand"
	"crypto/rsa"
	"crypto/x509"
	"encoding/json"
	"encoding/pem"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"sync"
	"testing"
)

// ssh asks each machine listed with an address how long it has held nothing: one idle ten minutes
// goes back, one starting or not answering keeps its route with no end, and one answering set up
// keeps its route with its end; only an address with no route before is forgotten. With no work
// marked one starting goes back too, and where ssh cannot run here the meter moves all the same.
func TestTheTickRoutesReadyRentalsAndGivesBackIdleOnes(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	ak := filepath.Join(home, ".agentkit")
	write := func(name, text string, mode os.FileMode) {
		t.Helper()
		path := filepath.Join(ak, name)
		if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(path, []byte(text), mode); err != nil {
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
	write("secrets/google-cloud.json", string(key), 0o600)
	write("secrets/google-cloud-ssh", "a key\n", 0o600)
	write("clock", "1793498400", 0o600) // 1 Nov 2026, 02:00 UTC
	t.Setenv("AK_GOOGLE_CLOCK", filepath.Join(ak, "clock"))
	t.Cleanup(func() { unanswered = nil })
	write("state/google-cloud-offers.json", `{"at": 1793491200, "offers": [["c4a-standard-8", "europe-west4", 8, 32768, 1.5,
		["europe-west4-a"], "projects/debian-cloud/global/images/family/debian-13-arm64", "hyperdisk-balanced"]]}`, 0o600)

	// Google: a token for any JWT, ak's machines listed, each read and deleted by name
	const project = "/compute/v1/projects/acme-build"
	var held sync.Mutex
	var listing []map[string]any
	var deleted []string
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
		case path == "/aggregated/instances":
			answer(map[string]any{"items": map[string]any{"zones/europe-west4-a": map[string]any{"instances": listing}}})
		case !strings.HasPrefix(path, "/zones/europe-west4-a/instances/") || at < 0:
			http.NotFound(w, r)
		case r.Method == http.MethodGet:
			answer(listing[at])
		default:
			deleted = append(deleted, name)
			listing = slices.Delete(listing, at, at+1)
			answer(map[string]any{})
		}
	}))
	defer google.Close()
	t.Setenv("AK_GOOGLE_URL", google.URL)
	rental := func(name, address string) map[string]any {
		return map[string]any{"id": name, "name": "acme-" + name, "labels": map[string]string{"ak": "rented"},
			"creationTimestamp": "2026-11-01T01:00:00Z", "machineType": "zones/europe-west4-a/machineTypes/c4a-standard-8",
			"scheduling":        map[string]any{"maxRunDuration": map[string]string{"seconds": "21600"}},
			"networkInterfaces": []any{map[string]any{"accessConfigs": []any{map[string]string{"natIP": address}}}}}
	}
	listing = []map[string]any{rental("idle", "203.0.113.1"), rental("starting", "203.0.113.2"),
		rental("silent", "203.0.113.3"), rental("busy", "203.0.113.4")}

	// ssh answering by alias, and ssh-keygen, each saying what it was asked
	bin := t.TempDir()
	t.Setenv("PATH", bin)
	script := func(name, body string) {
		if err := os.WriteFile(filepath.Join(bin, name), []byte("#!/bin/sh\n"+body), 0o700); err != nil {
			t.Fatal(err)
		}
	}
	script("ssh", `case "$*" in *" acme-busy "*) printf '%s\n' "$@" >"`+bin+`/busy";; esac
for word; do [ "$word" = -- ] && break; shift; done
case $2 in acme-idle) echo 600;; acme-starting) echo -1;; acme-busy) echo ' 0';; *) exit 255;; esac
`)
	script("ssh-keygen", `echo "$@" >>"`+bin+`/keygen"`)
	const line = "helper idle"
	secrets := filepath.Join(ak, "secrets")
	route := func(name, address, end string) string {
		if end != "" {
			end = "  # until " + end + "\n"
		}
		return "Host acme-" + name + "\n" + end + `  HostName "` + address + "\"\n  User \"ak\"\n" +
			`  IdentityFile "` + secrets + "/google-cloud-ssh\"\n  IdentitiesOnly \"yes\"\n" +
			`  UserKnownHostsFile "` + secrets + "/google-cloud-known-hosts\"\n  StrictHostKeyChecking \"accept-new\"\n"
	}
	const others = "Host *\n  Include ~/.ssh/config\n"
	write("state/google-cloud-ssh-config", route("idle", "203.0.113.1", "1793520000")+route("silent", "203.0.113.3", "")+
		route("busy", "203.0.113.4", "1793520000")+others, 0o600)
	// a pass with a config: what it gave back
	pass := func(config string) []string {
		t.Helper()
		write("config.toml", config, 0o600)
		os.Remove(filepath.Join(bin, "keygen"))
		held.Lock()
		deleted = nil
		held.Unlock()
		if carried, err := Watch(line); !carried || err != nil {
			t.Fatalf("carried %v, %v", carried, err)
		}
		held.Lock()
		defer held.Unlock()
		return deleted
	}

	if got := pass("[google_cloud]\nactive = false\nmax_month = 50\n"); !slices.Equal(got, []string{"acme-idle"}) {
		t.Errorf("given back %q", got)
	}
	if got := read("state/google-cloud-late.json"); got != "[\n  \"acme-idle listed idle, given back\"\n]\n" {
		t.Errorf("said %s", got)
	}
	routes := route("starting", "203.0.113.2", "") + route("silent", "203.0.113.3", "") + route("busy", "203.0.113.4", "1793516400")
	if got := read("state/google-cloud-ssh-config"); got != routes+others {
		t.Errorf("routes\n%s", got)
	}
	if got, _ := os.ReadFile(filepath.Join(bin, "keygen")); string(got) != "-R 203.0.113.2 -f "+secrets+"/google-cloud-known-hosts\n" {
		t.Errorf("ssh-keygen asked %q", got)
	}
	want := []string{"-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", `HostName="203.0.113.4"`, "-o", `User="ak"`,
		"-o", `IdentityFile="` + secrets + `/google-cloud-ssh"`, "-o", `IdentitiesOnly="yes"`,
		"-o", `UserKnownHostsFile="` + secrets + `/google-cloud-known-hosts"`, "-o", `StrictHostKeyChecking="accept-new"`,
		"--", "acme-busy", "if test -e /run/ak-ready; then helper idle; else echo -1; fi"}
	if got, _ := os.ReadFile(filepath.Join(bin, "busy")); string(got) != strings.Join(want, "\n")+"\n" {
		t.Errorf("ssh asked %q", got)
	}

	if got := pass("[google_cloud]\nactive = true\nmax_month = 50\nwork = []\n"); !slices.Equal(got, []string{"acme-starting"}) {
		t.Errorf("no work marked: given back %q", got)
	}
	if got := read("state/google-cloud-late.json"); got != "[\n  \"acme-starting listed no work marked, given back\"\n]\n" {
		t.Errorf("no work marked: said %s", got)
	}
	routes = route("silent", "203.0.113.3", "") + route("busy", "203.0.113.4", "1793516400")
	if got := read("state/google-cloud-ssh-config"); got != routes+others {
		t.Errorf("no work marked: routes\n%s", got)
	}
	if _, err := os.Stat(filepath.Join(bin, "keygen")); err == nil {
		t.Error("an address with a route was forgotten")
	}

	// no ssh here: none answers, none goes back for it, and the meter moves on
	t.Setenv("PATH", t.TempDir())
	write("clock", "1793502000", 0o600)
	given := pass("[google_cloud]\nactive = false\nmax_month = 50\n")
	routes = route("silent", "203.0.113.3", "") + route("busy", "203.0.113.4", "")
	if got := read("state/google-cloud-ssh-config"); len(given) != 0 || got != routes+others {
		t.Errorf("no ssh: given back %q, routes\n%s", given, got)
	}
	if got := read("state/google-cloud-ledger.json"); !strings.HasPrefix(got, "{\n  \"answered\": 1793502000.0,\n") {
		t.Errorf("no ssh: metered %s", got)
	}
}
