//go:build linux || darwin

package terminal

// Unread has the next ReadKeys answer keys, in order, before anything typed since: what a wait read
// while it held the screen, kept for the screen it opens.
func (k *Keyboard) Unread(keys ...Key) {
	k.unread = append(append([]Key(nil), keys...), k.unread...)
}
