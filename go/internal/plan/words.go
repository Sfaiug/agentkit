package plan

// Progress is how many of the plan's box lines are done, of how many (watch.plan_progress); none
// for no plan or one nothing can read.
func (look Look) Progress(name string) (done, total int) {
	lines, _ := look.read(name)
	for _, line := range lines {
		if boxed(line) {
			total++
			if !open(line) {
				done++
			}
		}
	}
	return done, total
}

// LastDone is the words of the plan's last done line (plan._done), "" where it holds none: what a
// seat whose plan owes nothing says it did.
func (look Look) LastDone(name string) (words string) {
	lines, _ := look.read(name)
	for _, line := range lines {
		if !boxed(line) || open(line) {
			continue
		}
		words = doneWords(line)
	}
	return words
}
