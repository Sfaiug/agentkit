package cli

import (
	"bufio"
	"fmt"
	"io"
	"os"
	"strings"
	"time"

	"agentkit/internal/menu"
	"agentkit/internal/terminal"
)

func pipeMenu(out, errOut io.Writer) int {
	found, known := readFrame(time.Now())
	if !known || found.handoff {
		return notImplemented(errOut, "attach")
	}
	screen := terminal.For(out)
	for _, line := range noticeLines(menuNotices(), screen.LayoutWidth()) {
		fmt.Fprintln(out, line)
	}
	view := menu.View{Screen: screen, Seats: found.seats, Cells: found.cells, Standing: found.standing,
		Clock: time.Now().Format("15:04"), Keys: menu.Keys(screen, len(found.past) > 0)}
	for _, line := range menu.Lines(view, screen.Width(), 1<<20) {
		fmt.Fprintln(out, line)
	}
	line, _ := bufio.NewReader(os.Stdin).ReadString('\n')
	switch strings.TrimSpace(line) {
	case "", "esc", "\x1b":
		return 0
	}
	return notImplemented(errOut, "attach")
}
