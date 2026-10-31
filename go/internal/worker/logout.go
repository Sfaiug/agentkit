package worker

import (
	"bytes"
	"context"
	"io"
	"os"
	"path/filepath"
	"time"

	"agentkit/internal/config"
)

// poll is how often a running turn's log is read: a file has no portable readiness notification.
const poll = time.Second

// A logout reads one turn's stderr.log for its harness's own logout words, its manifest's
// `[auth] signatures`: a turn that said one never reached the model, whatever its exit code.  The
// whole log, not its tail, as a harness that said it can then print a page of its own unwinding;
// each look reads on from where the last whole one ended, keeping the longest words' length less
// one, so words split between two looks are still found.
type logout struct {
	log   string
	marks []string
	keep  int
	read  int64
	carry []byte
}

func loggedOut(harness, out string) *logout {
	marks, _ := config.Words(harness, "auth", "signatures")
	words := &logout{log: filepath.Join(out, "stderr.log")}
	for _, mark := range marks {
		if mark != "" {
			words.marks = append(words.marks, mark)
			words.keep = max(words.keep, len(mark)-1)
		}
	}
	return words
}

// seen is the words the log holds by now, as the manifest spells them, read case-insensitively,
// or "".
func (words *logout) seen() string {
	if len(words.marks) == 0 {
		return ""
	}
	log, err := os.Open(words.log)
	if err != nil {
		return ""
	}
	defer log.Close()
	if _, err := log.Seek(words.read, io.SeekStart); err != nil {
		return ""
	}
	said, read, chunk := bytes.Clone(words.carry), words.read, make([]byte, 64<<10)
	for {
		n, err := log.Read(chunk)
		said, read = append(said, chunk[:n]...), read+int64(n)
		lower := bytes.ToLower(said)
		for _, mark := range words.marks {
			if bytes.Contains(lower, bytes.ToLower([]byte(mark))) {
				return mark
			}
		}
		said = said[max(0, len(said)-words.keep):]
		if err == io.EOF {
			words.read, words.carry = read, said
			return ""
		} else if err != nil {
			return ""
		}
	}
}

// watch is ctx, ended too once the log holds logout words, looked for each second: a turn that
// said it is logged out and then hangs, or streams on, ends at once.  The func ends the watch,
// waiting for a look in progress.
func (words *logout) watch(ctx context.Context) (context.Context, func()) {
	ctx, cancel := context.WithCancel(ctx)
	looked := make(chan struct{})
	go func() {
		defer close(looked)
		tick := time.NewTicker(poll)
		defer tick.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-tick.C:
				if words.seen() != "" {
					cancel()
				}
			}
		}
	}()
	return ctx, func() {
		cancel()
		<-looked
	}
}
