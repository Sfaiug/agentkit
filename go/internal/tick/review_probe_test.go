//go:build unix

package tick

import (
    "fmt"
    "io"
    "os"
    "path/filepath"
    "testing"
    "time"

    "agentkit/internal/history"
)

func TestReviewProbeRowWhenRunBecomesUnreadable(t *testing.T) {
    ak, _ := idleHome(t, "")
    dir := filepath.Join(ak, "runs", "fix-api")
    path := filepath.Join(dir, "run.json")
    put(t, path, fmt.Sprintf(`{"run_id":"fix-api","merged":true,"finished_at":%d,"pr":"https://github.com/acme/api/pull/1","merge_sha":"abc","repo":"/","health":{"command":"chmod 000 $HOME/.agentkit/runs/fix-api/run.json; exit 3"},"deployed":null}`, time.Now().Unix()))
    older(t, "PRAGMA user_version")
    t.Cleanup(func() { os.Chmod(path, 0600) })
    if err := checking(t, io.Discard).mergeChecks(); err != nil {
        t.Fatal(err)
    }
    if _, err := os.ReadFile(path); !os.IsPermission(err) {
        t.Fatalf("probe did not make run.json unreadable: %v", err)
    }
    db := history.Look()
    rows := db.Select("SELECT exit FROM checks WHERE run_id='fix-api' AND kind='health' AND tree='abc'")
    db.Close()
    if len(rows) != 1 || rows[0]["exit"] != int64(3) {
        t.Fatalf("ended probe lost its row when run.json became unreadable: %v", rows)
    }
}
