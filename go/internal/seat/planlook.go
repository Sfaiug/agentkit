package seat

// Progress is how many of the seat's plan's box lines are done, of how many, looked up as the
// reading that read the seat looks plans up.
func (seat Seat) Progress() (done, total int) { return seat.plans.Progress(seat.Name) }

// FirstDone is the words of the seat's plan's first done line: what a past seat set out to do and
// did.
func (seat Seat) FirstDone() string { return seat.plans.FirstDone(seat.Name) }
