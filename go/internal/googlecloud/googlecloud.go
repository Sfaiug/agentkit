// Package googlecloud is the machines ak rents from Google Cloud, as Python's google_cloud: what
// is offered (Offers, Keep, Kept) and the best of it (Best), what ak rents (Rented) and giving one
// back (GiveBack), the tick's pass metering this month's spend on them, giving back those it may
// not keep, routing ssh to the rest and renting for a need (Watch), and what that pass last said
// (Bill), in words another provider can be one more package of. It alone knows Google: the
// service-account key, the token its JWT buys, Compute Engine's Spot price list, machine types,
// machines and quota limits, how a call to Google fails, and the time it reads.
package googlecloud

import (
	"bytes"
	"cmp"
	"context"
	"crypto"
	"crypto/rsa"
	"crypto/sha256"
	"crypto/x509"
	"encoding/base64"
	"encoding/json"
	"encoding/pem"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"maps"
	"net/http"
	"net/http/httptrace"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"sync/atomic"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/host"
)

const (
	key = "google-cloud.json" // in ~/.agentkit/secrets
	// A project's own key may not read its billing account's currency (billingAccounts.get: 403).
	currency    = "EUR"
	computeSKUs = "6F81-5844-456A"                              // Compute Engine's service in the price list
	diskGB      = 20                                            // a boot disk holding the system, a checkout and its tests
	hoursAMonth = 730                                           // how Google turns a monthly price into an hourly one
	address     = "External IP Charge on a Spot Preemptible VM" // its region is "global"
	// The fewest vCPUs a rented machine has: in memory, its suite's image took 6.4 of a 2-vCPU
	// one's 7.8 GB, and a 4 ran 6 pieces in 4 hours to a 72's 2231 (2 Nov 2026).
	smallest = 8
	// A rented machine's boot image, "-arm64" for arm64.
	image = "projects/debian-cloud/global/images/family/debian-13"
)

var (
	// A page of the price list is 5,000 entries, on a host under load.
	client = &http.Client{Timeout: 30 * time.Second}
	// A Spot core or memory price of one machine family, e.g. "Spot Preemptible C4A Arm Instance
	// Core running in Netherlands"; a custom shape, named in it, costs more and is no type.
	spot = regexp.MustCompile(`^Spot Preemptible (\w+) (?:[\w-]+ )*?Instance (Core|Ram) running in `)
	// A boot disk's price, its GBs' unless the word is IOPS or Throughput.
	disk = regexp.MustCompile(`^(Balanced PD|Hyperdisk Balanced) (\w+) in `)
	// Each of those as a machine's boot disk names its type.
	diskTypes = map[string]string{"Balanced PD": "pd-balanced", "Hyperdisk Balanced": "hyperdisk-balanced"}
)

// Offer is a machine type to rent in a region.
type Offer struct {
	Name, Region string
	Cores        float64 // physical: an arm64 vCPU is one, two x86 vCPUs share one
	MemoryMB     int
	Hourly       float64 // euros: its cores, memory, boot disk and address, as the bill will
	// The zones of its region offering it, none in a list kept before ak rented, and its boot
	// disk's image and type.
	Zones       []string
	Image, Disk string
}

// CPUs is the vCPUs its machine counts, as a suite's VMs are given them.
func (o Offer) CPUs() float64 {
	if strings.HasSuffix(o.Image, "-arm64") {
		return o.Cores
	}
	return 2 * o.Cores
}

func (o Offer) String() string {
	return fmt.Sprintf("%s in %s · %s cores · %s GB · €%.3f an hour", o.Name, o.Region, host.Short(o.Cores),
		host.Short(float64(o.MemoryMB)/1024), o.Hourly)
}

// Best is the offers of at least smallest vCPUs and mbPerCPU of memory each, the lowest price a
// core first.
func Best(mbPerCPU int, offered []Offer) []Offer {
	fits := slices.DeleteFunc(slices.Clone(offered), func(o Offer) bool {
		return o.CPUs() < smallest || float64(o.MemoryMB) < float64(mbPerCPU)*o.CPUs()
	})
	slices.SortFunc(fits, func(a, b Offer) int {
		return cmp.Or(cmp.Compare(a.Hourly/a.Cores, b.Hourly/b.Cores), cmp.Compare(a.Name, b.Name),
			cmp.Compare(a.Region, b.Region))
	})
	return fits
}

// Offers is every machine type the price list prices, with the zones of its region offering it.
func Offers() ([]Offer, error) {
	compute, token, err := login()
	if err != nil {
		return nil, err
	}
	// by family or disk, and region; an address's the same in every one
	core, ram, disks := map[[2]string]float64{}, map[[2]string]float64{}, map[[2]string]float64{}
	ip, priced := 0.0, false
	err = pages(token, endpoint("cloudbilling", "/v1/services/"+computeSKUs+"/skus"),
		url.Values{"currencyCode": {currency}, "pageSize": {"5000"}}, func(page listing) {
			for _, raw := range page.Skus {
				var sku entry
				price, ok := sku.hourly(raw)
				if !ok {
					continue
				}
				if sku.Description == address {
					ip, priced = price, true
				}
				part, boot := spot.FindStringSubmatch(sku.Description), disk.FindStringSubmatch(sku.Description)
				for _, region := range sku.ServiceRegions {
					switch {
					case part != nil && !strings.Contains(sku.Description, "Custom"):
						prices := ram
						if part[2] == "Core" {
							prices = core
						}
						prices[[2]string{strings.ToLower(part[1]), region}] = price
					case boot != nil && !strings.HasPrefix(boot[2], "IOPS") && !strings.HasPrefix(boot[2], "Throughput"):
						disks[[2]string{boot[1], region}] = price
					}
				}
			}
		})
	if err != nil {
		return nil, err
	}
	var offered []Offer
	found := map[[2]string]int{} // at in offered
	err = pages(token, compute+"/aggregated/machineTypes", url.Values{"returnPartialSuccess": {"true"}}, func(page listing) {
		for _, listed := range slices.Sorted(maps.Keys(page.Items)) {
			zone := strings.TrimPrefix(listed, "zones/")
			region := regionOf(zone)
			for _, raw := range page.Items[listed].MachineTypes {
				var kind struct {
					Name, Architecture           string
					GuestCpus, MemoryMb          int
					IsSharedCpu                  bool
					Accelerators                 []any
					Deprecated, BundledLocalSsds map[string]any
				}
				if json.Unmarshal(raw, &kind) != nil {
					continue
				}
				family, _, _ := strings.Cut(kind.Name, "-")
				aCore, cored := core[[2]string{family, region}]
				aGB, rammed := ram[[2]string{family, region}]
				product, aDiskGB := "", 0.0
				for _, one := range bootDisks(family) {
					if price, ok := disks[[2]string{one, region}]; ok && (product == "" || price < aDiskGB) {
						product, aDiskGB = one, price
					}
				}
				// a shared core, an accelerator or a bundled local SSD is priced apart from the
				// cores, and bare metal is never Spot
				if kind.IsSharedCpu || len(kind.Accelerators) > 0 || len(kind.Deprecated) > 0 ||
					len(kind.BundledLocalSsds) > 0 || strings.HasSuffix(kind.Name, "-metal") ||
					kind.GuestCpus == 0 || kind.MemoryMb == 0 || !cored || !rammed || product == "" || !priced {
					continue
				}
				if at, ok := found[[2]string{kind.Name, region}]; ok {
					offered[at].Zones = append(offered[at].Zones, zone)
					continue
				}
				found[[2]string{kind.Name, region}] = len(offered)
				cores, booted := float64(kind.GuestCpus), image+"-arm64"
				if kind.Architecture != "ARM64" {
					cores, booted = cores/2, image
				}
				offered = append(offered, Offer{kind.Name, region, cores, kind.MemoryMb,
					float64(kind.GuestCpus)*aCore + float64(kind.MemoryMb)/1024*aGB + diskGB*aDiskGB + ip,
					[]string{zone}, booted, diskTypes[product]})
			}
		}
	})
	return offered, err
}

// bootDisks is what a series boots from, which neither the price list nor a machine type says:
// Google's older series Persistent Disk alone, C3, C3D, H3, M3 and Z3 either, every other
// Hyperdisk alone.
func bootDisks(family string) []string {
	switch family {
	case "c2", "c2d", "e2", "n1", "n2", "n2d", "t2a", "t2d":
		return []string{"Balanced PD"}
	case "c3", "c3d", "h3", "m3", "z3":
		return []string{"Balanced PD", "Hyperdisk Balanced"}
	}
	return []string{"Hyperdisk Balanced"}
}

// login is Compute Engine's address for the key's project and a token for its service account,
// bought with a JWT the key signs.
func login() (compute, token string, err error) {
	data, err := os.ReadFile(filepath.Join(config.Home(), "secrets", key))
	shown := "~/.agentkit/secrets/" + key
	if errors.Is(err, fs.ErrNotExist) {
		return "", "", errors.New("not set up: no Google service-account key at " + shown)
	}
	var account struct {
		ProjectID   string `json:"project_id"`
		ClientEmail string `json:"client_email"`
		PrivateKey  string `json:"private_key"`
	}
	audience, assertion := endpoint("oauth2", "/token"), ""
	if err == nil {
		err = json.Unmarshal(data, &account)
	}
	if err == nil {
		assertion, err = signed(account.ClientEmail, account.PrivateKey, audience)
	}
	if err != nil {
		return "", "", fmt.Errorf("cannot use %s: %w", shown, err)
	}
	var bought struct {
		AccessToken string `json:"access_token"`
	}
	err = call(http.MethodPost, audience, "", url.Values{"grant_type": {"urn:ietf:params:oauth:grant-type:jwt-bearer"},
		"assertion": {assertion}}, &bought)
	return endpoint("compute", "/compute/v1/projects/"+account.ProjectID), bought.AccessToken, err
}

// signed is the JWT, RS256, that buys email's service account a token at audience. Google issues
// a key as PKCS #8.
func signed(email, private, audience string) (string, error) {
	block, _ := pem.Decode([]byte(private))
	if block == nil {
		return "", errors.New("no PEM private key")
	}
	parsed, err := x509.ParsePKCS8PrivateKey(block.Bytes)
	if err != nil {
		return "", err
	}
	signer, ok := parsed.(*rsa.PrivateKey)
	if !ok {
		return "", errors.New("not an RSA key")
	}
	at, err := now()
	if err != nil {
		return "", err
	}
	issued := int64(at)
	header, _ := json.Marshal(map[string]string{"alg": "RS256", "typ": "JWT"})
	claims, _ := json.Marshal(map[string]any{"iss": email, "aud": audience, "iat": issued, "exp": issued + 3600,
		"scope": "https://www.googleapis.com/auth/cloud-platform"})
	unsigned := b64(header) + "." + b64(claims)
	digest := sha256.Sum256([]byte(unsigned))
	signature, err := rsa.SignPKCS1v15(nil, signer, crypto.SHA256, digest[:])
	return unsigned + "." + b64(signature), err
}

// listing is a page of one of Google's listings: the price list's entries, or each zone's
// machine types or machines.
type listing struct {
	Skus  []json.RawMessage
	Items map[string]struct {
		MachineTypes []json.RawMessage
		Instances    []instance
	}
	NextPageToken string
	Unreachables  []string
}

// pages hands each page of a listing to read; a page missing part of it fails it, as the
// cheapest offer, or a machine ak pays for, may be in that part.
func pages(token, address string, query url.Values, read func(listing)) error {
	for {
		var page listing
		if err := call(http.MethodGet, address+"?"+query.Encode(), token, nil, &page); err != nil {
			return err
		}
		if len(page.Unreachables) > 0 {
			return fmt.Errorf("asking Google failed: %s unreachable", strings.Join(page.Unreachables, ", "))
		}
		read(page)
		if page.NextPageToken == "" {
			return nil
		}
		query.Set("pageToken", page.NextPageToken)
	}
}

// call asks Google at address, with method, for its JSON into answer, sending sent: a form to its
// token endpoint, else JSON with token.
func call(method, address, token string, sent, answer any) error {
	if unanswered != nil {
		return unanswered
	}
	var body []byte
	var err error
	header := http.Header{"Authorization": {"Bearer " + token}}
	switch sent := sent.(type) {
	case nil:
	case url.Values:
		body, header = []byte(sent.Encode()), http.Header{"Content-Type": {"application/x-www-form-urlencoded"}}
	default:
		body, err = json.Marshal(sent)
		header.Set("Content-Type", "application/json")
	}
	var replied atomic.Bool // a byte of Google's reply came
	traced := httptrace.WithClientTrace(context.Background(),
		&httptrace.ClientTrace{GotFirstResponseByte: func() { replied.Store(true) }})
	var request *http.Request
	if err == nil {
		request, err = http.NewRequestWithContext(traced, method, address, bytes.NewReader(body))
	}
	if err != nil {
		return fmt.Errorf("asking Google failed: %w", err)
	}
	request.Header = header
	response, err := client.Do(request)
	if err != nil {
		return failure(err, replied.Load())
	}
	defer response.Body.Close()
	// all of it: a reply cut short of its length, or more after its JSON, is no answer
	data, err := io.ReadAll(response.Body)
	if response.StatusCode/100 != 2 { // Google's answer: 403 Forbidden, 404 Not Found ...
		_, reason, _ := strings.Cut(response.Status, " ")
		refused := &refusal{response.StatusCode, reason, nil}
		if refused.status < 500 && err == nil { // it did nothing of the request, and says why in its own codes
			refused.codes = codes(data)
		}
		return refused
	}
	if err == nil {
		err = json.Unmarshal(data, answer)
	}
	if err != nil {
		return failure(err, replied.Load())
	}
	return nil
}

// endpoint is a Google host's address for path; the answer key's fake answers for every host.
func endpoint(host, path string) string {
	return cmp.Or(os.Getenv("AK_GOOGLE_URL"), "https://"+host+".googleapis.com") + path
}

// entry is one of the price list's.
type entry struct {
	Description    string
	ServiceRegions []string
	PricingInfo    []struct {
		PricingExpression struct {
			UsageUnit   string
			TieredRates []struct {
				UnitPrice *struct {
					Units string
					Nanos float64
				}
			}
		}
	}
}

// hourly reads raw into e and is its steady price an hour, its last tier's: a Spot core's or
// GB's, a disk's GB's or an address's. False for an entry with none.
func (e *entry) hourly(raw json.RawMessage) (float64, bool) {
	if json.Unmarshal(raw, e) != nil || len(e.PricingInfo) == 0 {
		return 0, false
	}
	expression := e.PricingInfo[len(e.PricingInfo)-1].PricingExpression
	if len(expression.TieredRates) == 0 || expression.TieredRates[len(expression.TieredRates)-1].UnitPrice == nil {
		return 0, false
	}
	price := expression.TieredRates[len(expression.TieredRates)-1].UnitPrice
	units, err := strconv.ParseInt(cmp.Or(price.Units, "0"), 10, 64)
	if err != nil {
		return 0, false
	}
	amount := float64(units) + price.Nanos/1e9
	if strings.HasSuffix(expression.UsageUnit, "mo") {
		amount /= hoursAMonth
	}
	return amount, true
}

func b64(data []byte) string {
	return base64.RawURLEncoding.EncodeToString(data)
}
