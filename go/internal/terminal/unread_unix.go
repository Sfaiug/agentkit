//go:build linux || darwin

package terminal

// Unread has the next ReadKeys answer keys, in order, before anything typed since: what a wait read
// while it held the screen, kept for the screen it opens.
func (k *Keyboard) Unread(keys ...Key) {
	k.unread = append(append([]Key(nil), keys...), k.unread...)
}

// Drop lets go every key Unread kept: the screen after the wait takes none of them.
func (k *Keyboard) Drop() { k.unread = nil }
