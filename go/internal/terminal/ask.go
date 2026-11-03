package terminal

import (
	"fmt"
	"io"
	"os"
	"strings"

	"agentkit/internal/config"
)

// Esc is what Esc alone reads as, which every question takes as going back.
const Esc = "\x1b"

// Sequence is whether an answer is an arrow or another key that sends more than Esc's byte: no
// answer, and no word of error either.
func Sequence(answer string) bool {
	return strings.HasPrefix(answer, Esc) && answer != Esc
}

// Answer puts up the prompt and is the stripped line typed, "" for Enter and the end of input
// alike, as Python's orch._seat_read.  It reads stdin a byte at a time, so the next question and
// a harness handed this terminal find what was typed after the line.  A person's Enter ended the
// prompt's line on the screen; on anything else this does.
func Answer(out io.Writer, prompt string) string {
	fmt.Fprint(out, prompt)
	var line []byte
	byteRead := make([]byte, 1)
	for {
		n, err := os.Stdin.Read(byteRead)
		if n == 1 && byteRead[0] != '\n' {
			line = append(line, byteRead[0])
		}
		if err != nil || n == 1 && byteRead[0] == '\n' {
			break
		}
	}
	if file, ok := out.(*os.File); !ok || !isTerminal(file) {
		fmt.Fprintln(out)
	}
	return strings.TrimFunc(string([]rune(string(line))), config.Space)
}

// ChoiceLines is a question's choices as Python's terminal.ask sets them: `<number> <name>`
// joined by ` · `, each line leaving its two columns of indent room.
func ChoiceLines(names []string, room int) []string {
	var lines []string
	line := ""
	for i, name := range names {
		item := fmt.Sprintf("%d %s", i+1, name)
		if Cells(item)+2 > room {
			if line != "" {
				lines = append(lines, line)
				line = ""
			}
			lines = append(lines, Wrap(item, room-2)...)
			continue
		}
		added := item
		if line != "" {
			added = line + " · " + item
		}
		if line != "" && Cells(added)+2 > room {
			lines = append(lines, line)
			line = item
		} else {
			line = added
		}
	}
	if line != "" {
		lines = append(lines, line)
	}
	return lines
}

// PromptLines is a prompt wrapped on spaces so a bracket naming every worker breaks no name, the
// cursor's space kept (terminal.prompt_lines); only the last line waits for the answer.
func PromptLines(prompt string, room int) []string {
	room = max(1, room)
	if Cells(prompt) <= room {
		return []string{prompt}
	}
	body, pad := strings.CutSuffix(prompt, " ")
	lines := Wrap(body, room)
	if len(lines) == 0 {
		lines = []string{body}
	}
	if pad {
		if last := len(lines) - 1; Cells(lines[last])+1 <= room {
			lines[last] += " "
		} else {
			lines = append(lines, " ")
		}
	}
	return lines
}
