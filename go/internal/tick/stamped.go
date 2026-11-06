package tick

import (
	"io"
	"os"
	"regexp"
	"strings"
	"time"
	"unicode/utf8"
)

// lineBreak is what Python's splitlines reads as the end of a line.
var lineBreak = regexp.MustCompile("\\r\\n|[\\n\\r\\v\\f\\x1c\\x1d\\x1e\\x{85}\\x{2028}\\x{2029}]")

// stamp is the stream as the tick writes it: where the log owns it, dated as Python's stamp_log
// dates the streams it finds the log as the tick begins; a terminal's reader sees each line as it
// comes, so a stream elsewhere is left as it is.
func (l *log) stamp(stream io.Writer) io.Writer {
	if file, ok := stream.(*os.File); ok && l.owned[file] {
		return &stamping{stream: file, last: "\n"}
	}
	return stream
}

// stamping is a stream of the tick's into its log (watch.Stamped): each line written to it, blank
// or not, whoever writes it, a WARN on stderr among them, starts with its date and time, so two
// lines say how long what lay between them took.
type stamping struct {
	stream io.Writer
	last   string // the character written last
}

func (s *stamping) Write(p []byte) (int, error) {
	stamp := time.Now().Format("2006-01-02 15:04:05 ")
	var dated strings.Builder
	for text := string(p); text != ""; {
		end := len(text)
		if at := lineBreak.FindStringIndex(text); at != nil {
			end = at[1]
		}
		line := text[:end]
		text = text[end:]
		// the character before decides too: a CR ends its line, and an LF written after it ends
		// that same line, starting none
		if lineBreak.MatchString(s.last) && !(s.last == "\r" && line[0] == '\n') {
			dated.WriteString(stamp)
		}
		dated.WriteString(line)
		_, size := utf8.DecodeLastRuneInString(line)
		s.last = line[len(line)-size:]
	}
	if _, err := io.WriteString(s.stream, dated.String()); err != nil {
		return 0, err
	}
	return len(p), nil
}
