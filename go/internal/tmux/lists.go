package tmux

import "slices"

// message is what one call to tmux may carry (orch.TMUX_MESSAGE).
const message = 15 * 1024

// Lists runs those command lists on one server in as few calls as a message takes (orch.tmux_lists):
// tmux stops a call at the first command that fails, so the lists sent with one that did are then
// run one by one, each setting what it can.  Its error is the first failure's.
func Lists(server string, lists [][]string) (failed error) {
	var calls [][][]string
	size := 0
	for _, words := range lists {
		wide := width(words)
		if len(calls) == 0 || size+wide > message {
			calls = append(calls, nil)
			size = 0
		}
		calls[len(calls)-1] = append(calls[len(calls)-1], words)
		size += wide
	}
	for _, sent := range calls {
		var joined []string
		for i, words := range sent {
			if i > 0 {
				joined = append(joined, ";")
			}
			joined = append(joined, words...)
		}
		err := list(server, joined)
		if err != nil && len(sent) > 1 {
			err = nil
			for _, words := range sent {
				if alone := list(server, words); alone != nil && err == nil {
					err = alone
				}
			}
		}
		if failed == nil {
			failed = err
		}
	}
	return failed
}

// list runs one command list in a call, or one longer than a message carries a command a call, to
// the first that fails, as tmux runs a list (orch.tmux_options): what follows a refused command,
// a bar's digest among it, is never set.
func list(server string, words []string) error {
	if width(words) <= message {
		_, err := run(server, words...)
		return err
	}
	for len(words) > 0 {
		end := slices.Index(words, ";")
		if end < 0 {
			end = len(words)
		}
		if _, err := run(server, words[:end]...); err != nil {
			return err
		}
		words = words[min(end+1, len(words)):]
	}
	return nil
}

// width is what a command list takes of a call's message, the `;` before it included.
func width(words []string) int {
	wide := 2
	for _, word := range words {
		wide += len(word) + 1
	}
	return wide
}
