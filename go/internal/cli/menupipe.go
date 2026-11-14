package cli

import (
	"bufio"
	"fmt"
	"io"
	"os"
	"strings"
	"time"

	"agentkit/internal/commandhelp"
	"agentkit/internal/menu"
	"agentkit/internal/terminal"
)

func pipeMenu(dry, overlay bool, out, errOut io.Writer) int {
	found, said, known := openedFrame(dry || overlay)
	if !known {
		return notImplemented(errOut, "attach")
	}
	screen, own, in := terminal.For(out), popupSeat(overlay), bufio.NewReader(os.Stdin)
	for {
		for _, line := range noticeLines(append(said, menuNotices()...), screen.LayoutWidth()) {
			fmt.Fprintln(out, line)
		}
		said = nil
		view := menu.View{Screen: screen, Seats: found.seats, Cells: found.cells, Standing: found.standing,
			Clock: time.Now().Format("15:04"), Keys: menuKeys(screen, &found, own), Pipe: true}
		for _, line := range menu.Lines(view, screen.Width(), 0) {
			fmt.Fprintln(out, line)
		}
		line, _ := in.ReadString('\n')
		key := strings.ToLower(strings.TrimSpace(line))
		switch {
		case key == "" || key == "\x1b": // an empty line, the end of input or Esc leaves
			return 0
		case strings.HasPrefix(key, "\x1b"): // an arrow key is neither Esc nor a key: drawn again
		case pipeTakes(key, &found, own):
			return notImplemented(errOut, "attach")
		default:
			fmt.Fprintf(out, "not a key: %s\n%s\n", commandhelp.Quote(key), view.Keys)
		}
	}
}
