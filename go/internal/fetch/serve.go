package fetch

import (
	"bufio"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"time"
)

const (
	heartbeat = "heartbeat"
	// The Mac beats every 5 seconds; three missed beats mean it slept or lost the network.
	silence = 15 * time.Second
)

var (
	requestID = regexp.MustCompile(`^[a-f0-9]{16}$`)
	errHeld   = errors.New("another connection holds serve.lock; exiting")
)

// serve hands the Mac each pending request as `<id>\t<path>`, once the Mac has beaten, until it
// hangs up or falls silent. One connection owns the queue for its entire lifetime: a reconnect
// waits until the old connection closes or its heartbeat expires, even if sshd lives on.
func serve(in io.Reader, out, errOut io.Writer) int {
	root, err := bridge()
	if err != nil {
		fmt.Fprintln(errOut, "ak fetch: "+err.Error())
		return 2
	}
	lock, err := lockServe(filepath.Join(root, "serve.lock"))
	if errors.Is(err, errHeld) {
		fmt.Fprintln(errOut, "ak fetch --serve: "+err.Error())
		return 0
	}
	if err != nil {
		fmt.Fprintln(errOut, "ak fetch: "+err.Error())
		return 2
	}
	defer lock.Close()
	beats := make(chan struct{})
	go func() {
		defer close(beats)
		reader := bufio.NewReader(in)
		// Only a whole heartbeat line counts; a longer line is cut short to bound memory.
		var line []byte
		for {
			b, err := reader.ReadByte()
			if err != nil {
				return
			}
			if b != '\n' {
				if len(line) <= len(heartbeat) {
					line = append(line, b)
				}
				continue
			}
			if string(line) == heartbeat {
				beats <- struct{}{}
			}
			line = line[:0]
		}
	}()
	quiet := time.NewTimer(silence)
	tick := time.NewTicker(poll)
	sent := make(chan error, 1)
	connected, sending := false, ""
	for {
		select {
		case _, open := <-beats:
			if !open {
				// A line already being written may have reached the Mac: settle it first.
				if sending == "" {
					return 0
				}
				beats, connected = nil, false
				continue
			}
			connected = true
			quiet.Reset(silence)
		case <-quiet.C:
			// A write still blocked after the Mac fell silent never reached it; its request stays queued.
			return 0
		case err := <-sent:
			sending = ""
			if err != nil || beats == nil {
				return 0
			}
		case <-tick.C:
		}
		if connected && sending == "" {
			var line string
			if sending, line = next(filepath.Join(root, "requests"), errOut); sending != "" {
				go func(request string) {
					// Only a whole line hands the request off; a failed write leaves it for the next connection.
					_, err := io.WriteString(out, line)
					if err == nil {
						os.Remove(request)
					}
					sent <- err
				}(sending)
			}
		}
	}
}

// next is the first pending request and its line; one that cannot be sent is dropped and named.
func next(requests string, errOut io.Writer) (string, string) {
	entries, _ := os.ReadDir(requests)
	for _, entry := range entries {
		if !requestID.MatchString(entry.Name()) {
			continue
		}
		request := filepath.Join(requests, entry.Name())
		data, err := os.ReadFile(request)
		if err != nil {
			continue // a fetch timed out during this scan
		}
		var asked struct {
			Path *string `json:"path"`
		}
		if err = json.Unmarshal(data, &asked); err == nil && (asked.Path == nil || strings.ContainsAny(*asked.Path, "\x00\r\n\t")) {
			err = errors.New("invalid request path")
		}
		if err != nil {
			os.Remove(request)
			fmt.Fprintf(errOut, "ak fetch --serve: invalid request %s: %s\n", entry.Name(), err)
			continue
		}
		return request, entry.Name() + "\t" + *asked.Path + "\n"
	}
	return "", ""
}
