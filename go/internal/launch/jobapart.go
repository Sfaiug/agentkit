package launch

import (
	"cmp"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"

	"agentkit/internal/host"
	"agentkit/internal/job"
	"agentkit/internal/loop"
	"agentkit/internal/run"
)

// detach is the rest of a `--bg` job's launch, Python's spawn_job_bg: `ak run resume <job>`
// started in a session and unit of its own, the job's directory in its AGENTKIT_JOB_DIR, and its
// pid written on the receipt under the job's recovery lock, which the child reads the receipt
// under before it adopts it (ownChild); then the job's id and receipt said.  `ak run`'s exit
// status, and why the job's launcher did not start.
func detach(dir string, out io.Writer) (int, string, error) {
	self, err := os.Executable()
	if err != nil {
		return 0, "", err
	}
	capMB, err := run.MemoryCapMB(host.SliceMemoryMax())
	if err != nil {
		return 0, "", err
	}
	release, err := run.Hold(dir)
	if err != nil {
		return 0, "", err
	}
	defer release()
	receipt, err := job.Read(dir)
	if receipt == nil {
		return 0, "", cmp.Or(err, errors.New("job.json cannot be read"))
	}
	id := filepath.Base(dir)
	child := exec.Command(self, "run", "resume", id)
	child.Env = append(os.Environ(), "AGENTKIT_JOB_DIR="+dir)
	pid, scope, reason, err := host.Place(child, filepath.Join(dir, "log.txt"), "agentkit-job-"+id, host.Limits(capMB, host.RunWeight), true)
	if err != nil {
		return 2, "could not launch the job: " + err.Error(), nil
	}
	run.SetAll(receipt, "pid", pid, "process_identity", loop.Identity(pid), "scope", scope, "scope_reason", nil, "memory_cap_mb", capMB)
	if scope == "none" {
		receipt.Set("scope_reason", reason)
		receipt.Delete("memory_cap_mb")
	}
	if err := job.Write(dir, receipt); err != nil {
		return 0, "", err
	}
	fmt.Fprintf(out, "%s\n%s\n", id, job.ReceiptPath(id))
	return 0, "", nil
}

// ownChild is whether this process is the launcher detach started for the job at dir, Python's
// cmd_job_resume own_child: the receipt's launcher alive, AGENTKIT_JOB_DIR naming the job, and the
// pid its own.
func ownChild(dir string, receipt *run.Object) bool {
	pid, _ := receipt.Int("pid")
	return !receipt.Truthy("finished_at") && run.ProcessActive(receipt) && os.Getenv("AGENTKIT_JOB_DIR") == dir && pid == os.Getpid()
}

// adopt carries the job on as its own launcher, Python's cmd_job_resume of its own child: from the
// directory the job was launched in, where a task naming no repository finds its checkout, on the
// options its receipt keeps.  `ak run`'s exit status.
func adopt(dir string, receipt *run.Object, out io.Writer) (int, error) {
	if cwd := receipt.Str("cwd"); cwd != "" {
		if info, err := os.Stat(cwd); err == nil && info.IsDir() {
			os.Chdir(cwd)
		}
	}
	j := &jobRun{dir: dir, receipt: receipt, values: map[string]string{}, flags: map[string]bool{}, out: out, say: jobLogger(dir, out)}
	opts := receipt.Dict("opts")
	for _, flag := range jobValues {
		if given, ok := opts.Get(flag).(string); ok {
			j.values[flag] = given
		}
	}
	for _, flag := range jobSwitches {
		j.flags[flag] = opts.Truthy(flag)
	}
	code, err := j.carry()
	if errors.Is(err, job.ErrStopped) {
		fmt.Fprintf(out, "%s was stopped; nothing to resume\n", j.id())
		return 1, nil
	}
	return code, err
}
