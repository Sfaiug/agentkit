package loop

import (
	"io"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strings"
	"unicode/utf8"

	"agentkit/internal/config"
	"agentkit/internal/handin"
	"agentkit/internal/run"
)

const (
	refusalCap = 1000 // a refusal replaces the answer, so it is short; past this what is there is an answer
	echoLength = 40   // a prompt is recognised quoted back by this many of its own first characters
)

var (
	answerHeading = regexp.MustCompile(`(?m)^\s{0,3}#{1,6}\s`)
	eventFailed   = regexp.MustCompile(`(?i)error|fail|abort`)
)

// A record's kind fields, the output of the work it quotes, and the files in a turn's directory
// that are no harness talking: what it was told, the bookkeeping, the records and the answer.
var (
	eventKinds  = []string{"type", "subtype", "kind", "status", "state", "level"}
	eventOutput = []string{"aggregated_output", "output", "stdout", "stderr", "command", "content", "arguments", "tool_result", "input"}
	notHarness  = []string{"prompt.md", "session_id", handin.File, "review.md", "findings.json", "final.md"}
)

// fileTail is the last of a file, as text: an event log can be far too big to read whole.
func fileTail(path string) string {
	file, err := os.Open(path)
	if err != nil {
		return ""
	}
	defer file.Close()
	if end, err := file.Seek(0, io.SeekEnd); err == nil {
		file.Seek(max(0, end-outCap), io.SeekStart)
	}
	data, _ := io.ReadAll(file)
	return decoded(data)
}

// answers is whether text is the worker's answer rather than a refusal in its place, Python's
// answered: a refusal is the whole of what the harness managed to say, and it is short.
func answers(text string) bool {
	return utf8.RuneCountInString(text) > refusalCap || answerHeading.MatchString(text)
}

// withoutOutput is the node with every command's and tool's output cut out, at any depth: that
// text is the work's own, and a task that greps for a refusal's words is not one.
func withoutOutput(node any) any {
	switch value := node.(type) {
	case *run.Object:
		kept := run.NewObject()
		for _, key := range value.Keys() {
			if !slices.Contains(eventOutput, key) {
				kept.Set(key, withoutOutput(value.Get(key)))
			}
		}
		return kept
	case []any:
		kept := make([]any, len(value))
		for i, item := range value {
			kept[i] = withoutOutput(item)
		}
		return kept
	}
	return node
}

// isFailure is whether the record says of itself that it is a failure, at any depth.
func isFailure(node any) bool {
	switch value := node.(type) {
	case []any:
		return slices.ContainsFunc(value, isFailure)
	case *run.Object:
		for _, key := range value.Keys() {
			if (key == "error" || key == "is_error") && value.Truthy(key) {
				return true
			}
			if text, ok := value.Get(key).(string); ok && slices.Contains(eventKinds, key) && eventFailed.MatchString(text) {
				return true
			}
			if isFailure(value.Get(key)) {
				return true
			}
		}
	}
	return false
}

// isTerminal is whether the record is the run's own terminal report, the kind its manifest's
// `[stall] terminal` names, at any depth.
func isTerminal(node any, terminal string) bool {
	if terminal == "" {
		return false
	}
	switch value := node.(type) {
	case []any:
		return slices.ContainsFunc(value, func(item any) bool { return isTerminal(item, terminal) })
	case *run.Object:
		for _, key := range value.Keys() {
			if value.Get(key) == any(terminal) && slices.Contains(eventKinds, key) || isTerminal(value.Get(key), terminal) {
				return true
			}
		}
	}
	return false
}

// recordText is every string a record says, in one place: its kinds name it, and say nothing.
func recordText(node any) string {
	switch value := node.(type) {
	case string:
		return value
	case []any:
		parts := make([]string, len(value))
		for i, item := range value {
			parts[i] = recordText(item)
		}
		return strings.Join(parts, "\n")
	case *run.Object:
		var parts []string
		for _, key := range value.Keys() {
			if !slices.Contains(eventKinds, key) {
				parts = append(parts, recordText(value.Get(key)))
			}
		}
		return strings.Join(parts, "\n")
	}
	return ""
}

// oneLine is the node as json.dumps writes it with ensure_ascii off, every control character and
// line separator in its text a space: the only escapes left end in neither a letter nor a digit,
// so no word runs into one, and the record stays one line.
func oneLine(node any) string {
	switch value := node.(type) {
	case string:
		spaced := strings.Map(func(r rune) rune {
			if r < 0x20 || 0x7f <= r && r < 0xa0 || r == 0x2028 || r == 0x2029 {
				return ' '
			}
			return r
		}, value)
		return `"` + strings.NewReplacer(`\`, `\\`, `"`, `\"`).Replace(spaced) + `"`
	case []any:
		parts := make([]string, len(value))
		for i, item := range value {
			parts[i] = oneLine(item)
		}
		return "[" + strings.Join(parts, ", ") + "]"
	case *run.Object:
		parts := make([]string, 0, len(value.Keys()))
		for _, key := range value.Keys() {
			parts = append(parts, oneLine(key)+": "+oneLine(value.Get(key)))
		}
		return "{" + strings.Join(parts, ", ") + "}"
	}
	return run.Line(node)
}

// failures is the failure records of an event log, each minus the work's output, Python's failures:
// the terminal record is kept beside them, as with an empty final.md it is the only place a refusal
// can be, unless it is an answer.  With terminalOnly, on a clean exit, only the terminal record's
// failure or unanswered text speaks, so an earlier stream warning cannot discard an answer.
func failures(chunk, terminal string, terminalOnly, handedIn bool) []string {
	var records []string
	for _, line := range config.SplitLines(chunk) {
		line = strings.TrimFunc(line, config.Space)
		if !strings.HasPrefix(line, "{") {
			continue
		}
		decoded, err := run.Decode([]byte(line))
		if _, isRecord := decoded.(*run.Object); err != nil || !isRecord {
			continue
		}
		record := withoutOutput(decoded)
		final := isTerminal(record, terminal)
		unanswered := final && !handedIn && !answers(recordText(record))
		if terminalOnly && final && (isFailure(record) || unanswered) || !terminalOnly && (isFailure(record) || unanswered) {
			records = append(records, oneLine(record))
		}
	}
	return records
}

// harnessSaid is what the harness itself said this attempt, the work's own output kept out of it,
// Python's harness_said: the answer where nothing answered, its diagnostics and its event log, as a
// refusal lands in a different one on each harness.  With failuresOnly, on a clean exit, only a
// terminal refusal speaks, as a harness may log a retried warning before a good answer.
func harnessSaid(out, text, terminal string, failuresOnly bool) string {
	first, _, _ := strings.Cut(handin.Answer(filepath.Join(out, "prompt.md")), "\n")
	first, _, _ = strings.Cut(first, `"`)
	first, _, _ = strings.Cut(first, `\`)
	echo := strings.TrimFunc(first, config.Space)
	if len(echo) < echoLength {
		echo = ""
	}
	submitted, _ := handin.Read(filepath.Join(out, handin.File))
	handedIn := submitted != nil && (submitted.Closing() != nil || failuresOnly)
	if failuresOnly && !handedIn && answers(text) {
		return ""
	}
	var parts []string
	if !failuresOnly && !handedIn && !answers(text) {
		parts = append(parts, text)
	}
	entries, _ := os.ReadDir(out)
	for _, entry := range entries {
		if slices.Contains(notHarness, entry.Name()) || !entry.Type().IsRegular() {
			continue
		}
		chunk := fileTail(filepath.Join(out, entry.Name()))
		if filepath.Ext(entry.Name()) == ".jsonl" {
			parts = append(parts, failures(chunk, terminal, failuresOnly, handedIn)...)
		} else if !failuresOnly {
			runes := []rune(chunk)
			parts = append(parts, string(runes[max(0, len(runes)-refusalCap):]))
		}
	}
	var lines []string
	for _, part := range parts {
		for _, line := range config.SplitLines(part) {
			if strings.TrimFunc(line, config.Space) != "" && (echo == "" || !strings.Contains(line, echo)) {
				lines = append(lines, line)
			}
		}
	}
	return strings.Join(lines, "\n")
}
