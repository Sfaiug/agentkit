package googlecloud

import (
	"cmp"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"os"
	"slices"
	"strconv"
	"strings"
	"time"

	"agentkit/internal/host"
)

const (
	askEvery      = 86400                    // seconds a quota's last ask stands: Google answered in minutes on 2 Nov 2026
	service       = "compute.googleapis.com" // whose quotas are asked for
	justification = "Spot machines running this project's test suites: the vCPUs in use plus one more machine"
)

// A room is what Google's quotas leave a rent: each quota's limit, the vCPUs every machine Google
// lists holds of it, ak's or not, and the quotas offers were passed over for, in turn.
type room struct {
	limits, used map[string]float64
	full         []string
}

// A lack is a quota an offer passed over would take past its limit, and the vCPUs it would hold.
type lack struct {
	quota string
	vcpus int
	limit float64
}

// A preference is Cloud Quotas' own record of the last ask for a quota.
type preference struct {
	Name, Service, Etag, QuotaID string
	Dimensions                   map[string]string
	UpdateTime                   time.Time
	Reconciling                  bool
	QuotaConfig                  struct{ PreferredValue, GrantedValue json.Number } // strings of digits, 0 left out
}

// roomFor is the room Google's quotas leave a rent of offered, read for it: a limit raised shows at
// once. A type's vCPUs are as offered in any region, none for one not offered (google_cloud._rent).
func roomFor(compute, token string, offered []Offer) (*room, error) {
	r := &room{limits: limits(offered), used: map[string]float64{}}
	cpus := map[string]float64{}
	for _, o := range offered {
		cpus[o.Name] = o.CPUs()
	}
	return r, pages(token, compute+"/aggregated/instances", url.Values{}, func(page listing) {
		for zone, listed := range page.Items {
			for _, one := range listed.Instances {
				kind := one.MachineType[strings.LastIndexByte(one.MachineType, '/')+1:]
				for _, quota := range r.against(kind, regionOf(strings.TrimPrefix(zone, "zones/"))) {
					r.used[quota] += cpus[kind]
				}
			}
		}
	})
}

// against is the quotas a machine of type kind in region counts against: its family's there, the
// most specific Google lists, and all regions'; none of -1, Google's no limit (google_cloud._quotas).
func (r *room) against(kind, region string) []string {
	family, _, _ := strings.Cut(kind, "-")
	family = strings.ToUpper(family)
	var counted []string
	for _, quota := range []string{family + " in " + region, family + "_CPUS in " + region, "CPUS in " + region} {
		if _, ok := r.limits[quota]; ok {
			counted = append(counted, quota)
			break
		}
	}
	return slices.DeleteFunc(append(counted, "CPUS_ALL_REGIONS"), func(quota string) bool {
		limit, ok := r.limits[quota]
		return !ok || limit < 0
	})
}

// short is what o lacks, none where its machine fits; each quota it lacks is full.
func (r *room) short(o Offer) []lack {
	var lacking []lack
	for _, quota := range r.against(o.Name, o.Region) {
		if vcpus := r.used[quota] + o.CPUs(); vcpus > r.limits[quota] {
			lacking = append(lacking, lack{quota, int(vcpus), r.limits[quota]})
			if !slices.Contains(r.full, quota) {
				r.full = append(r.full, quota)
			}
		}
	}
	return lacking
}

// String is the rent's line on the quotas it passed offers over for.
func (r *room) String() string {
	words := make([]string, len(r.full))
	for n, quota := range r.full {
		words[n] = fmt.Sprintf("%s: %s of %s vCPUs in use", quota, host.Short(r.used[quota]), host.Short(r.limits[quota]))
	}
	return "too little quota left: " + strings.Join(words, "; ")
}

// ask is the lines on what Google is asked for, its answer never awaited, after a rent that skipped
// offers for what they lack, cheapest first (google_cloud._ask): each of Compute's preferences
// Google finished granting short, then the quotas of the first skipped with any due, one Google
// holds no preference of or last updated askEvery ago, each asked for what it lacks. A failure is
// its line and nothing more, a call Google does not answer leaving the next its own try.
func ask(skipped [][]lack, at float64) []any {
	if len(skipped) == 0 {
		return nil
	}
	was := unanswered
	defer func() { unanswered = was }()
	var account struct {
		ProjectID   string `json:"project_id"`
		ClientEmail string `json:"client_email"`
	}
	_, token, err := login()
	var data []byte
	if err == nil {
		data, err = os.ReadFile(secret(key))
	}
	if err == nil {
		err = json.Unmarshal(data, &account)
	}
	preferences := endpoint("cloudquotas", "/v1/projects/"+account.ProjectID+"/locations/global/quotaPreferences")
	kept := map[string]preference{}
	var said []any
	if err == nil {
		err = pages(token, preferences, url.Values{}, func(page listing) {
			for _, one := range page.QuotaPreferences {
				if one.Service != service {
					continue
				}
				kept[one.quota()] = one
				asked, _ := one.QuotaConfig.PreferredValue.Int64()
				granted, _ := one.QuotaConfig.GrantedValue.Int64()
				if !one.Reconciling && granted < asked {
					said = append(said, fmt.Sprintf("%s: Google granted %d of the %d vCPUs asked", one.quota(), granted, asked))
				}
			}
		})
	}
	if err != nil {
		return []any{"no quota asked for: " + err.Error()}
	}
	var due []lack
	for _, lacking := range skipped {
		if due = slices.DeleteFunc(slices.Clone(lacking), func(one lack) bool {
			last, ok := kept[one.quota]
			return ok && at-float64(last.UpdateTime.UnixMicro())/1e6 < askEvery
		}); len(due) > 0 {
			break
		}
	}
	for _, one := range due {
		id, dimensions := preferred(one.quota)
		asked := map[string]any{"service": service, "quotaId": id, "dimensions": dimensions,
			"quotaConfig":  map[string]string{"preferredValue": strconv.Itoa(one.vcpus)},
			"contactEmail": account.ClientEmail, "justification": justification}
		if last, ok := kept[one.quota]; ok {
			asked["name"], asked["etag"] = last.Name, last.Etag
			err = call(http.MethodPatch, endpoint("cloudquotas", "/v1/"+last.Name+
				"?updateMask=quotaConfig.preferredValue,contactEmail,justification"), token, asked, new(any))
		} else {
			err = call(http.MethodPost, preferences, token, asked, new(any))
		}
		unanswered = was
		words := fmt.Sprintf("%s: %d vCPUs asked of Google, the limit now %s", one.quota, one.vcpus, host.Short(one.limit))
		if err != nil {
			words += ": " + err.Error()
		}
		said = append(said, words)
	}
	return said
}

// preferred is Cloud Quotas' quotaId and dimensions of a quota as against names it
// (google_cloud._preference).
func preferred(quota string) (string, map[string]string) {
	metric, region, regional := strings.Cut(quota, " in ")
	switch {
	case !regional:
		return "CPUS-ALL-REGIONS-per-project", map[string]string{}
	case strings.HasSuffix(metric, "CPUS"): // CPUS, N2_CPUS
		return strings.ReplaceAll(metric, "_", "-") + "-per-project-region", map[string]string{"region": region}
	}
	return "CPUS-PER-VM-FAMILY-per-project-region", map[string]string{"region": region, "vm_family": metric}
}

// quota is the preference's quota as against names it: preferred turned round (google_cloud._named).
func (p preference) quota() string {
	metric := cmp.Or(p.Dimensions["vm_family"], strings.ReplaceAll(strings.TrimSuffix(
		strings.TrimSuffix(p.QuotaID, "-per-project-region"), "-per-project"), "-", "_"))
	if region, ok := p.Dimensions["region"]; ok {
		return metric + " in " + region
	}
	return metric
}
