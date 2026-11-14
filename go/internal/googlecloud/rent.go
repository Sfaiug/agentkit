package googlecloud

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"slices"
	"strconv"
	"strings"
	"time"

	"agentkit/internal/run"
)

const (
	life = 12 * 3600 // a Spot machine is replaced at no cost, and a forgotten one costs no more
	// a rent's creates, polled 2 s apart each: one ran 40 s on 31 Oct 2026
	tries, polls = 4, 30
	// A machine's setup, each line run on those that served suites on 31 Oct 2026: docker's data
	// and trees in memory, as on disk a suite's cores idled in disk wait; sshd keeps a piece's
	// connection, and its penalties off, as 40 connections that never logged in made each ssh from
	// here exit 255 at once (tried on 2 Nov 2026, the day 247 pieces went so in 3 minutes): only
	// ak's key gets in.
	startup = `#!/bin/bash
set -e
useradd -m -s /bin/bash %[1]s
mkdir -p /var/lib/docker ~%[1]s/.agentkit-helper ~%[1]s/.ssh
mount -t tmpfs -o size=70%% tmpfs /var/lib/docker
mount -t tmpfs -o size=70%% tmpfs ~%[1]s/.agentkit-helper
echo '%[2]s' >~%[1]s/.ssh/authorized_keys
chown -R %[1]s: ~%[1]s
apt-get update -q && DEBIAN_FRONTEND=noninteractive apt-get install -qy docker.io docker-cli git jq
usermod -aG docker %[1]s
printf 'MaxStartups 500:30:1000\nPerSourcePenalties no\n' >/etc/ssh/sshd_config.d/ak.conf
systemctl reload ssh
touch %[3]s
`
)

// refusals is Google's codes for a zone's quota or stock being out, where the rent moves on.
var refusals = []string{"QUOTA_EXCEEDED", "quotaExceeded", "ZONE_RESOURCE_POOL_EXHAUSTED",
	"ZONE_RESOURCE_POOL_EXHAUSTED_WITH_DETAILS"}

// rent is how renting a machine of wanted MiB a vCPU went, in a line, as Python's _rent: the best
// offers in turn, each in the zones without a machine of listed first, as Google took both Spot
// machines of one zone in 6 s on 30 Oct 2026; living what the cap leaves, money; on the meter by
// name from before it is asked for until Google says it made none. A refusal of quota or stock
// moves on, up to tries creates; any other ends the rent.
func rent(ledger *run.Object, wanted int, cap, money float64, offered []Offer, listed []Machine) (string, error) {
	compute, token, err := login()
	if err != nil {
		return "", err
	}
	key, err := os.ReadFile(secret("google-cloud-ssh") + ".pub") // the public half of the key idle made
	if err != nil {
		return "", err
	}
	taken := map[string]bool{}
	for _, one := range listed {
		taken[one.Zone] = true
	}
	said, remaining := fmt.Sprintf("nothing offered with %d MiB a vCPU", wanted), tries
	for _, o := range Best(wanted, offered) {
		seconds := int(min(life, money*3600/o.Hourly))
		if seconds < ready {
			said = fmt.Sprintf("rents nothing: €%.2f of €%.2f spent this month or held to the machines' ends "+
				"leaves less than %d minutes of %s", cap-money, cap, ready/60, o.Name)
			continue
		}
		var free, held []string
		for _, zone := range o.Zones {
			if taken[zone] {
				held = append(held, zone)
			} else {
				free = append(free, zone)
			}
		}
		for _, zone := range append(free, held...) {
			random := make([]byte, 6)
			rand.Read(random)
			name := "ak-" + hex.EncodeToString(random)
			asked, err := now() // past refusals' polls
			if err != nil {
				return "", err
			}
			ledger.Dict("machines").Set(name, run.Fields("price", o.Hourly, "from", asked, "until", asked+float64(seconds)))
			if err := save(meterPath(), run.Encode(ledger)+"\n"); err != nil {
				return "", err
			}
			refused, err := create(compute, token, zone, machine(name, zone, o, seconds, strings.TrimSpace(string(key))))
			if err != nil {
				return fmt.Sprintf("%s asked for in %s, kept on the meter: %v", name, zone, err), nil
			}
			if refused == nil {
				return fmt.Sprintf("%s rented: %s in %s", name, o.Name, zone), nil
			}
			ledger.Dict("machines").Delete(name)
			if err := save(meterPath(), run.Encode(ledger)+"\n"); err != nil {
				return "", err
			}
			said, remaining = fmt.Sprintf("%s in %s refused: %s", o.Name, zone, strings.Join(refused.codes, " ")), remaining-1
			if remaining == 0 || !slices.ContainsFunc(refused.codes, func(code string) bool { return slices.Contains(refusals, code) }) {
				return said, nil
			}
		}
	}
	return said, nil
}

// create asks Google to make machine in zone: nil once it is made, or Google refusing with its
// codes, where it made none; an error where it may have made it: no answer, one cut short, a
// refusal of 500 or more, or none made after polls polls (google_cloud._create).
func create(compute, token, zone string, machine any) (*refusal, error) {
	var answer json.RawMessage
	err := call(http.MethodPost, compute+"/zones/"+zone+"/instances", token, machine, &answer)
	if refused := (*refusal)(nil); errors.As(err, &refused) && refused.status < 500 {
		return refused, nil
	}
	for polled := 0; err == nil; polled++ {
		var operation struct {
			Status, Name string
			Error        json.RawMessage
		}
		json.Unmarshal(answer, &operation) // an operation of no such fields is not done
		switch {
		case operation.Status == "DONE" && operation.Error != nil:
			return &refusal{codes: codes(answer)}, nil
		case operation.Status == "DONE":
			return nil, nil
		case polled == polls:
			return nil, fmt.Errorf("Google had not made it after %d polls", polls)
		}
		time.Sleep(2 * time.Second)
		err = call(http.MethodGet, compute+"/zones/"+zone+"/operations/"+operation.Name, token, nil, &answer)
	}
	return nil, err
}

// machine is what Google is asked to make (google_cloud._machine): Spot, deleted by Google itself
// at its end whatever becomes of this host, its boot disk with it, with one address, reached by
// key, the public half of ak's, alone.
func machine(name, zone string, o Offer, seconds int, key string) map[string]any {
	return map[string]any{"name": name, "machineType": "zones/" + zone + "/machineTypes/" + o.Name,
		"labels": map[string]string{"ak": "rented"}, "scheduling": map[string]any{
			"provisioningModel": "SPOT", "instanceTerminationAction": "DELETE",
			"maxRunDuration": map[string]string{"seconds": strconv.Itoa(seconds)}, "automaticRestart": false,
			"onHostMaintenance": "TERMINATE"},
		"disks": []any{map[string]any{"boot": true, "autoDelete": true, "initializeParams": map[string]string{
			"sourceImage": o.Image, "diskSizeGb": strconv.Itoa(diskGB),
			"diskType": "zones/" + zone + "/diskTypes/" + o.Disk}}},
		"networkInterfaces": []any{map[string]any{"accessConfigs": []any{map[string]string{"type": "ONE_TO_ONE_NAT"}}}},
		"metadata": map[string]any{"items": []any{map[string]string{"key": "block-project-ssh-keys", "value": "true"},
			map[string]string{"key": "startup-script", "value": fmt.Sprintf(startup, user, key, setUp)}}}}
}
