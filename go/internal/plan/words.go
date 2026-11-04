package plan

// Progress is how many of the plan's box lines are done, of how many (watch.plan_progress); none
// for no plan or one nothing can read.
func Progress(name string) (done, total int) {
	lines, _ := read(name)
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
func LastDone(name string) (words string) {
	lines, _ := read(name)
	for _, line := range lines {
		if !boxed(line) || open(line) {
			continue
		}
		words = doneWords(line)
	}
	return words
}
