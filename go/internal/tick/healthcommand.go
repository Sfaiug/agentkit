package tick

import (
	"bufio"
	"context"
	"fmt"
	"io"
	"os"
	"os/exec"
	"slices"
	"strings"
	"time"
	"unicode/utf8"

	"agentkit/internal/config"
	"agentkit/internal/gitcall"
	"agentkit/internal/host"
)

// window is how much of a probe's output is read: its end, from the start of its last line.
const window = 4096

// healthCommand is a live probe as Python's watch.health_command runs one: `bash -c command` in
// repo, sha its AK_MERGE_SHA, killed with all it started at timeout or once it exits, so no pipe
// it inherited holds the tick.  Whether it passed, and the last ten lines it wrote.
func healthCommand(repo, sha, command string, timeout time.Duration) (bool, string) {
	output, err := os.CreateTemp("", "")
	if err != nil {
		return false, config.PyError(err)
	}
	defer os.Remove(output.Name())
	defer output.Close()
	limited, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	cmd := exec.CommandContext(limited, "bash", "-c", command)
	cmd.Dir, cmd.Env, cmd.Stdout, cmd.Stderr = repo, append(os.Environ(), "AK_MERGE_SHA="+sha), output, output
	stop := host.Group(cmd)
	if err := cmd.Start(); err != nil {
		return false, config.PyError(err)
	}
	failed := cmd.Wait()
	timedOut := limited.Err() != nil
	stop() // even a shell that exited can have left children
	said, err := tail(output)
	if err != nil {
		return false, config.PyError(err)
	}
	if timedOut {
		said += fmt.Sprintf("\ntimed out after %ds", timeout/time.Second)
	}
	return failed == nil && !timedOut, strings.TrimFunc(said, config.Space)
}

// tail is the last ten lines of output, read from the start of its last line where that begins
// before the window, which says why; decoded as the whole output decodes, so a character the
// window begins inside comes whole, and one it cuts off is held back unless the output ends.
func tail(output *os.File) (string, error) {
	size, err := output.Seek(0, io.SeekEnd)
	if err != nil {
		return "", err
	}
	start := max(0, size-window)
	if start > 0 {
		if begun, found := lastLine(bufio.NewReader(io.NewSectionReader(output, 0, size))); found {
			start = min(start, begun)
		}
	}
	from := max(0, start-(utf8.UTFMax-1))
	read := make([]byte, start-from+window)
	n, err := output.ReadAt(read, from)
	if err != nil && err != io.EOF {
		return "", err
	}
	primer, data := read[:start-from], read[start-from:n]
	data = slices.Concat(primer[len(primer)-unfinished(primer):], data)
	if from+int64(n) < size {
		data = data[:len(data)-unfinished(data)]
	}
	lines := config.SplitLines(strings.TrimRightFunc(gitcall.Decoded(string(data)), config.Space))
	return strings.Join(lines[max(0, len(lines)-10):], "\n"), nil
}

// lastLine is where the line holding the last character that is no space begins, past the line
// break before it, and whether there is one.
func lastLine(output *bufio.Reader) (int64, bool) {
	var at, after, begun int64
	found := false
	for {
		r, n, err := output.ReadRune()
		if err != nil {
			return begun, found
		}
		at += int64(n)
		if strings.ContainsRune("\n\r\v\f\x1c\x1d\x1e\u0085\u2028\u2029", r) {
			after = at
		} else if !config.Space(r) {
			begun, found = after, true
		}
	}
}

// unfinished is how many of data's last bytes begin a character they do not finish, which a
// decoder holds back for what comes next.
func unfinished(data []byte) int {
	for n := 1; n < utf8.UTFMax && n <= len(data); n++ {
		if !utf8.FullRune(data[len(data)-n:]) {
			return n
		}
	}
	return 0
}
