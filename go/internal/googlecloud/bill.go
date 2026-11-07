package googlecloud

import (
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/run"
)

const pass = 180 // seconds between the tick's passes: cron's */3 (install.sh)

// Bill is `ak doctor`'s lines on the machines ak rents while it may, none while it may not, as
// Python's google_cloud.said: the meter as the tick's last answer left it, the machines Google
// has listed on it running, then the lines the tick left on those it gave back. An answer older
// than two passes says when it came, in local time. False where the tick's lines are not a list
// of them or Google's clock cannot be read, which Python says in its own words.
func Bill() ([]string, bool) {
	active, cap := config.CloudBudget()
	if !active {
		return nil, true
	}
	var late []string
	data, err := os.ReadFile(latePath())
	if err == nil {
		err = json.Unmarshal(data, &late)
	}
	if err != nil && !errors.Is(err, fs.ErrNotExist) {
		return nil, false
	}
	ledger, read := meter()
	if !read {
		return append([]string{"cannot read ~/.agentkit/state/google-cloud-ledger.json: all machines go back"}, late...), true
	}
	answered, _ := ledger.Num("answered")
	if answered == 0 {
		return []string{"Google has not answered the tick yet"}, true
	}
	at, err := now()
	if err != nil {
		return nil, false
	}
	spent, _ := ledger.Num("spent")
	said := fmt.Sprintf("%d running · €%.2f of €%.2f this month", running(ledger), spent, cap)
	if at-answered > 2*pass {
		said += " as of " + time.Unix(int64(answered), 0).Format("2 Jan 15:04")
	}
	return append([]string{said}, late...), true
}

// running is how many machines on the meter Google has listed: one on it by name has `from`.
func running(ledger *run.Object) int {
	count := 0
	for _, key := range ledger.Dict("machines").Keys() {
		if !ledger.Dict("machines").Dict(key).Has("from") {
			count++
		}
	}
	return count
}

// latePath is where the tick says what it did with the machines it gave back, apart from the
// meter, so a meter that cannot be read hides no refusal.
func latePath() string { return filepath.Join(config.Home(), "state", "google-cloud-late.json") }
