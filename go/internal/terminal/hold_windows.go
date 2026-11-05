package terminal

// GiveHeld starts the program that stands in for this one: on Windows nothing is held.
func (k *Keyboard) GiveHeld(start func() error) error { return start() }

// While runs work: nothing is taken to answer for meanwhile.
func (k *Keyboard) While(work func()) { work() }
