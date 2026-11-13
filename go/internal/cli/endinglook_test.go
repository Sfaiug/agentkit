package cli

import (
	"bufio"
	"bytes"
	"io"
	"path/filepath"
	"testing"

	"agentkit/internal/run"
)

type failedLookOutput struct{ short bool }

func (out failedLookOutput) Write(data []byte) (int, error) {
	if out.short {
		return len(data) / 2, nil
	}
	return 0, io.ErrClosedPipe
}

func TestAFailedLookLeavesItsEndingForTheTick(t *testing.T) {
	for name, output := range map[string]func() io.Writer{
		"failed write": func() io.Writer { return failedLookOutput{} },
		"short write":  func() io.Writer { return failedLookOutput{short: true} },
		"failed flush": func() io.Writer { return bufio.NewWriterSize(failedLookOutput{}, 65536) },
	} {
		for _, verb := range []string{"status", "wait"} {
			t.Run(name+"/"+verb, func(t *testing.T) {
				home := sandbox(t)
				t.Setenv("AGENTKIT_SESSION", "acme")
				t.Setenv("AK_HOST_READINGS", `{"free_mb":4096,"mem_total_mb":16384,"load":1,"cpus":8}`)
				dir := filepath.Join(home, ".agentkit", "runs", "r")
				write(t, filepath.Join(dir, "run.json"), `{"state":"fail","error":"Missing row","launched_session":"acme","handback_pending":true}`)
				var errOut bytes.Buffer
				var code int
				if verb == "wait" {
					code = Main([]string{"wait", "r"}, &errOut, output())
				} else {
					code = Main([]string{"run", "status", "r"}, output(), &errOut)
				}
				record, _ := run.Read(dir)
				if code != 1 || !run.Waits(record) || record.Truthy("handed_back") {
					t.Fatalf("exit=%d record=%s stderr=%s", code, run.Line(record), errOut.String())
				}
			})
		}
	}
}
