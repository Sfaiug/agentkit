package googlecloud

import (
	"cmp"
	"encoding/json"
	"fmt"
	"maps"
	"net/http"
	"slices"
	"strconv"
	"strings"
)

// families is Service Usage's limits on a family's vCPUs in each region, of a project; FULL lists
// every region's, not only those changed.
const families = "/v1beta1/projects/%s/services/compute.googleapis.com/consumerQuotaMetrics/" +
	"compute.googleapis.com%%2Fcpus_per_vm_family?view=FULL"

// limits is the vCPUs Google lets the project hold of each quota, named as Python's _quotas names
// them, in the regions offered: a family's in a region, a region's CPUS metrics, and
// CPUS_ALL_REGIONS (google_cloud._limits). None if any cannot be read, as a less specific one would
// hold a family instead; Google not answering leaves the rent its own calls, as Compute answered
// the listing.
func limits(offered []Offer) map[string]float64 {
	defer func(was error) { unanswered = was }(unanswered)
	compute, token, err := login()
	var buckets struct {
		ConsumerQuotaLimits []struct {
			QuotaBuckets []struct {
				EffectiveLimit json.Number // a string of digits
				Dimensions     map[string]string
			}
		}
	}
	if err == nil {
		err = call(http.MethodGet, endpoint("serviceusage", fmt.Sprintf(families, compute[strings.LastIndexByte(compute, '/')+1:])),
			token, nil, &buckets)
	}
	if err != nil {
		return nil
	}
	found := map[string]float64{}
	for _, limit := range buckets.ConsumerQuotaLimits {
		for _, bucket := range limit.QuotaBuckets {
			family, ok := bucket.Dimensions["vm_family"]
			region, in := bucket.Dimensions["region"]
			if !ok || !in {
				continue
			}
			// Google's answer leaves out a limit of 0 (H4D in most regions, 2 Nov 2026)
			vcpus, err := strconv.ParseInt(cmp.Or(bucket.EffectiveLimit.String(), "0"), 10, 64)
			if err != nil {
				return nil
			}
			found[family+" in "+region] = float64(vcpus)
		}
	}
	regions := map[string]bool{}
	for _, o := range offered {
		regions[o.Region] = true
	}
	type quotas struct {
		Quotas []struct {
			Metric string
			Limit  float64
		}
	}
	for _, region := range slices.Sorted(maps.Keys(regions)) {
		var listed quotas
		if call(http.MethodGet, compute+"/regions/"+region, token, nil, &listed) != nil {
			return nil
		}
		for _, quota := range listed.Quotas {
			if strings.HasSuffix(quota.Metric, "CPUS") {
				found[quota.Metric+" in "+region] = quota.Limit
			}
		}
	}
	var project quotas
	if call(http.MethodGet, compute, token, nil, &project) != nil {
		return nil
	}
	for _, quota := range project.Quotas {
		if quota.Metric == "CPUS_ALL_REGIONS" {
			found[quota.Metric] = quota.Limit
		}
	}
	return found
}
