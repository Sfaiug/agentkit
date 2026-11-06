package googlecloud

import (
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"

	"agentkit/internal/config"
)

// served is a machine the tick found ready, in the ssh config it keeps of the machines ak rents.
var served = regexp.MustCompile(`(?m)^Host (.+)\n  # until (\d+)$`)

// A Rental is a machine ak rents that serves: its ssh alias and when it ends, a Unix time.
type Rental struct {
	Name  string
	Until int64
}

// Serving is each machine ak rents that serves, as the tick last found them ready, while ak may
// rent (google_cloud.serving).
func Serving() []Rental {
	if active, _ := config.CloudBudget(); !active {
		return nil
	}
	var rentals []Rental
	for _, found := range served.FindAllStringSubmatch(routes(), -1) {
		until, _ := strconv.ParseInt(found[2], 10, 64)
		rentals = append(rentals, Rental{found[1], until})
	}
	return rentals
}

// SSHConfig is the ssh options that reach a machine ak rents, even while renting is off; none
// for another alias, which keeps ssh's own config (google_cloud.ssh_config).
func SSHConfig(alias string) []string {
	if alias == "" || !strings.Contains(routes(), "Host "+alias+"\n") {
		return nil
	}
	return []string{"-F", routesPath()}
}

// routes is the ssh config's text, routes finishing work while renting is off included.
func routes() string {
	data, _ := os.ReadFile(routesPath())
	return string(data)
}

func routesPath() string { return filepath.Join(config.Home(), "state", "google-cloud-ssh-config") }
