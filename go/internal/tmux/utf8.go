package tmux

import (
	"os"
	"strings"
)

// utf8 is what makes a call a UTF-8 client: nothing where its locale already does, as tmux reads
// one, the first of LC_ALL, LC_CTYPE and LANG that is set naming UTF-8, and otherwise `-u`.
// $TMUX, which tmux also reads, never reaches a call (command).
func utf8() []string {
	for _, name := range []string{"LC_ALL", "LC_CTYPE", "LANG"} {
		if locale := strings.ToUpper(os.Getenv(name)); locale != "" {
			if strings.Contains(locale, "UTF-8") || strings.Contains(locale, "UTF8") {
				return nil
			}
			break
		}
	}
	return []string{"-u"}
}
