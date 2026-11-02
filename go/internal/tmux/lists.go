package tmux

// message is what one call to tmux may carry (orch.TMUX_MESSAGE).
const message = 15 * 1024

// Lists runs those command lists on one server in as few calls as a message takes (orch.tmux_lists):
// tmux stops a call at the first command that fails, so the lists sent with one that did are then
// run one by one, each setting what it can.  Its error is the first failure's.
func Lists(server string, lists [][]string) (failed error) {
	var calls [][][]string
	size := 0
	for _, words := range lists {
		wide := 2 // the `;` before it
		for _, word := range words {
			wide += len(word) + 1
		}
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
		_, err := run(server, joined...)
		if err != nil && len(sent) > 1 {
			err = nil
			for _, words := range sent {
				if _, alone := run(server, words...); alone != nil && err == nil {
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
