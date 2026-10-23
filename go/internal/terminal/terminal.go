// Package terminal handles presentation without invoking host tools.
package terminal

import (
	"io"
	"os"
	"strings"
)

func Dim(out io.Writer, text string) string {
	file, ok := out.(*os.File)
	term := os.Getenv("TERM")
	_, noColor := os.LookupEnv("NO_COLOR")
	if !ok || !isTerminal(file) || noColor || term == "" || term == "dumb" {
		return text
	}
	code := "2"
	color := strings.ToLower(os.Getenv("COLORTERM"))
	if color == "truecolor" || color == "24bit" {
		code = "2;38;2;108;112;134"
	} else if strings.Contains(term, "256color") {
		code = "2;38;5;243"
	}
	return "\x1b[" + code + "m" + text + "\x1b[0m"
}
