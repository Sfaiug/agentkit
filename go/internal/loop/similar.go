package loop

// similarity is how alike two lines read, Python's difflib.SequenceMatcher(None, a, b).ratio():
// twice the matching characters over all of them, the longest common block first and then those
// either side of it, the earliest where blocks tie.
func similarity(a, b string) float64 {
	first, second := []rune(a), []rune(b)
	if len(first)+len(second) == 0 {
		return 1
	}
	return 2 * float64(matching(first, second, positions(second))) / float64(len(first)+len(second))
}

// positions is where each character stands in b, without those difflib's autojunk leaves out: in a
// text of at least 200, one making up more than 1% of it.
func positions(b []rune) map[rune][]int {
	found := map[rune][]int{}
	for at, char := range b {
		found[char] = append(found[char], at)
	}
	if len(b) >= 200 {
		for char, at := range found {
			if len(at) > len(b)/100+1 {
				delete(found, char)
			}
		}
	}
	return found
}

// matching is how many characters a and b match in order, by those positions.
func matching(a, b []rune, where map[rune][]int) int {
	var count func(aFrom, aTo, bFrom, bTo int) int
	count = func(aFrom, aTo, bFrom, bTo int) int {
		bestA, bestB, size := aFrom, bFrom, 0
		lengths := map[int]int{}
		for i := aFrom; i < aTo; i++ {
			next := map[int]int{}
			for _, j := range where[a[i]] {
				if j < bFrom {
					continue
				}
				if j >= bTo {
					break
				}
				k := lengths[j-1] + 1
				next[j] = k
				if k > size {
					bestA, bestB, size = i-k+1, j-k+1, k
				}
			}
			lengths = next
		}
		// a block grows over what autojunk left out, as difflib's does
		for bestA > aFrom && bestB > bFrom && a[bestA-1] == b[bestB-1] {
			bestA, bestB, size = bestA-1, bestB-1, size+1
		}
		for bestA+size < aTo && bestB+size < bTo && a[bestA+size] == b[bestB+size] {
			size++
		}
		if size == 0 {
			return 0
		}
		return size + count(aFrom, bestA, bFrom, bestB) + count(bestA+size, aTo, bestB+size, bTo)
	}
	return count(0, len(a), 0, len(b))
}
