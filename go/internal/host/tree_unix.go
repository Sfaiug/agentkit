//go:build unix

package host

import (
	"io"
	"os"
)

// EndTree ends that process and everything below it, Python's watch.kill_tree.
func EndTree(pid int) {
	end(func() []int { return below(pid) }, io.Discard)
}

// below is that process and every process under it, this one aside.
func below(pid int) []int {
	children := map[int][]int{}
	for _, each := range processes() {
		if stat, ok := ReadStat(each); ok {
			children[stat.Parent] = append(children[stat.Parent], each)
		}
	}
	var found []int
	for stack := []int{pid}; len(stack) > 0; {
		last := stack[len(stack)-1]
		stack = stack[:len(stack)-1]
		if last != os.Getpid() {
			found = append(found, last)
			stack = append(stack, children[last]...)
		}
	}
	return found
}
