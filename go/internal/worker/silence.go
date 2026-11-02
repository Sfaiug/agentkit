package worker

import (
	"bytes"
	"io"
	"os"
	"strings"

	"agentkit/internal/host"
	"agentkit/internal/run"
)

// Heard is Written, or with heartbeats the count of whole lines of no such `type`: those only say
// a tool still runs, so a hung tool call heartbeating away still goes silent.
func Heard(path string, heartbeats []string) func() any {
	if len(heartbeats) == 0 {
		return host.Written(path)
	}
	var at int64
	var rest []byte
	said := 0
	beat := func(line []byte) bool {
		value, _ := run.Decode(line)
		event, _ := value.(*run.Object)
		if event == nil {
			return false
		}
		for _, kind := range heartbeats {
			if event.Str("type") == kind {
				return true
			}
		}
		return false
	}
	return func() any {
		file, err := os.Open(path)
		if err != nil {
			return said
		}
		defer file.Close()
		if end, err := file.Seek(0, io.SeekEnd); err != nil {
			return said
		} else if end < at {
			at, rest = 0, nil // rewritten from its start
		}
		file.Seek(at, io.SeekStart)
		more, _ := io.ReadAll(file)
		at += int64(len(more))
		lines := bytes.Split(append(rest, more...), []byte("\n"))
		rest = lines[len(lines)-1]
		for _, line := range lines[:len(lines)-1] {
			if strings.TrimSpace(string(line)) != "" && !beat(line) {
				said++
			}
		}
		return said
	}
}
