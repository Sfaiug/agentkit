package loop

import (
	"os"
	"path/filepath"

	"agentkit/internal/config"
	"agentkit/internal/suitetimes"
)

// timed times versions of checkout's commits for suitetimes.Refusal, Python's suite_times.timed:
// each version's files run just them (AK_ONLY) at its commit, one after another in one clone of
// checkout, each file's own, whatever became of the others.  A run that moved or edited its
// checkout timed something else, and times none.  None is kept: an older commit lacks the files
// the change adds, and would drop their times from the record.
func (l *loop) timed(checkout string) suitetimes.Timer {
	return func(command string, versions ...suitetimes.Version) ([]map[string]float64, error) {
		if err := config.EnsureDirs(); err != nil {
			return nil, err
		}
		tmp, err := os.MkdirTemp(filepath.Join(config.Home(), "tmp"), "timing-")
		if err != nil {
			return nil, err
		}
		defer os.RemoveAll(tmp)
		clone, log := filepath.Join(tmp, "checkout"), filepath.Join(tmp, "timed.log")
		if err := l.git(checkout).CloneBorrowing(clone, "--no-checkout"); err != nil {
			return nil, err
		}
		c := l.git(clone)
		var found []map[string]float64
		for _, version := range versions {
			sha, err := l.git(checkout).Must("rev-parse", version.Ref+"^{commit}")
			if err != nil {
				return nil, err
			}
			for _, args := range [][]string{{"checkout", "--quiet", "--force", "--detach", sha}, {"clean", "-fdqx"}} {
				if _, err := c.Must(args...); err != nil {
					return nil, err
				}
			}
			output, err := os.Create(log)
			if err != nil {
				return nil, err
			}
			_, err = l.boxed(clone, command, "", "", l.ceiling, output, log, false, false, version.Files)
			output.Close()
			if err != nil {
				return nil, err
			}
			head, err := c.Try("rev-parse", "HEAD")
			if err != nil {
				return nil, err
			}
			edited, _, err := c.Out("diff", "--quiet", "HEAD")
			if err != nil {
				return nil, err
			}
			times := map[string]float64{}
			if head == sha && edited == 0 {
				times = measured(log, 0)
			}
			found = append(found, times)
		}
		return found, nil
	}
}
