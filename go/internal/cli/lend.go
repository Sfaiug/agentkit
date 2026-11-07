package cli

import (
	"context"
	"fmt"
	"io"
	"os"
	"os/signal"
	"strings"

	"agentkit/internal/host"
	"agentkit/internal/lend"
	"agentkit/internal/run"
)

// lendHome is `ak lend [--subscriptions] <home>`, a check's own, as Python's lend.main: home lent
// each harness's login (lend.Into), a line per harness lent, its name and the paths it placed
// there, and asked for subscriptions a last line, the JSON {provider: account} of each lent by
// name.  No <home> is a traceback in Python, left to it.
func lendHome(args []string, out, errOut io.Writer) int {
	subscriptions := len(args) > 0 && args[0] == "--subscriptions"
	if subscriptions {
		args = args[1:]
	}
	if len(args) == 0 {
		return notImplemented(errOut, "lend")
	}
	host.Mark("ak lend")
	// Ctrl-C takes back what was lent, as Python's KeyboardInterrupt does on its way out; after,
	// it ends ak at once, nothing left to take back, even with a full stdout blocking a print
	interrupt, stop := signal.NotifyContext(context.Background(), os.Interrupt)
	loan, err := lend.Into(interrupt, args[0], subscriptions)
	interrupted := interrupt.Err() != nil
	stop()
	if interrupted {
		fmt.Fprintln(errOut, "\nak lend: interrupted")
		return 130
	}
	if err != nil {
		fmt.Fprintf(errOut, "lend: %s\n", err)
		return 1
	}
	for _, lent := range loan.Lent {
		fmt.Fprintln(out, strings.Join(lent, " "))
	}
	if subscriptions {
		fmt.Fprintln(out, run.Line(loan.Named))
	}
	return 0
}
