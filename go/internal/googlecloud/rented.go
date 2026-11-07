package googlecloud

import (
	"encoding/json"
	"maps"
	"net/http"
	"net/url"
	"slices"
	"strings"
	"time"
)

// A Machine is one ak rents, as Google lists it (google_cloud.Rented): its id outlives a rename.
type Machine struct {
	ID, Name, Zone, Type string
	Created, Until       float64 // Unix seconds: its creation, and that plus the life it was given
	Address              string  // its external address, none before Google gives it one
}

// instance is a machine as Compute Engine answers it.
type instance struct {
	ID, Name, MachineType string
	CreationTimestamp     time.Time
	Labels                map[string]string
	Scheduling            struct{ MaxRunDuration struct{ Seconds json.Number } } // a string of digits
	NetworkInterfaces     []struct{ AccessConfigs []struct{ NatIP string } }
}

func (one instance) ours() bool { return one.Labels["ak"] == "rented" }

// Rented is what Google says ak has now: every machine labelled ak=rented, in every zone, all of
// them or none, as ak may be paying for one in a zone left out.
func Rented() ([]Machine, error) {
	compute, token, err := login()
	if err != nil {
		return nil, err
	}
	var found []Machine
	err = pages(token, compute+"/aggregated/instances", url.Values{}, func(page listing) {
		for _, zone := range slices.Sorted(maps.Keys(page.Items)) {
			for _, one := range page.Items[zone].Instances {
				if !one.ours() {
					continue
				}
				created := float64(one.CreationTimestamp.UnixMicro()) / 1e6
				life, _ := one.Scheduling.MaxRunDuration.Seconds.Int64() // none: no life given
				address := ""
				for _, nic := range one.NetworkInterfaces {
					if len(nic.AccessConfigs) > 0 {
						address = nic.AccessConfigs[0].NatIP
						break
					}
				}
				found = append(found, Machine{one.ID, one.Name, strings.TrimPrefix(zone, "zones/"),
					one.MachineType[strings.LastIndexByte(one.MachineType, '/')+1:], created,
					created + float64(life), address})
			}
		}
	})
	if err != nil {
		return nil, err
	}
	return found, nil
}

// GiveBack deletes machine, its boot disk and address with it, where Google, asked again, still
// names it by its id and labels it ak's; one Google no longer has is gone already.
func GiveBack(machine Machine) error {
	compute, token, err := login()
	if err != nil {
		return err
	}
	address := compute + "/zones/" + machine.Zone + "/instances/" + machine.Name
	var found instance
	if err := call(http.MethodGet, address, token, nil, &found); err != nil || found.ID != machine.ID || !found.ours() {
		return gone(err)
	}
	return gone(call(http.MethodDelete, address, token, nil, new(any)))
}
