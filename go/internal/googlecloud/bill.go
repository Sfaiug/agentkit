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
	said, err := asOf(answered, 2*pass)
	if err != nil {
		return nil, false
	}
	spent, _ := ledger.Num("spent")
	said = fmt.Sprintf("%d running · €%.2f of €%.2f this month", running(ledger), spent, cap) + said
	return append([]string{said}, late...), true
}

// Cheapest is `ak doctor`'s line on the machines ak rents while it may not, as Python's
// google_cloud.said: the best of the offers the tick last kept, a list kept more than a day ago
// saying when, in local time. Google is asked only where no list is kept or its `at` is no time
// ak could have written: a listing takes a minute, more than ak's live probe, which runs `ak
// doctor`, may take.
func Cheapest(mbPerCPU int) string {
	at, offered := Kept()
	said, err := asOf(at, freshFor)
	if len(offered) == 0 || !possible(at) {
		said = ""
		offered, err = Offers()
	}
	if err != nil {
		return err.Error()
	}
	if best := Best(mbPerCPU, offered); len(best) > 0 {
		return "best now " + best[0].String() + said
	}
	return "nothing offered"
}

// asOf is when an answer came, in local time, for one given more than fresh seconds ago.
func asOf(at, fresh float64) (string, error) {
	when, err := now()
	if err != nil || when-at <= fresh {
		return "", err
	}
	return " as of " + time.Unix(int64(at), 0).Format("2 Jan 15:04"), nil
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
