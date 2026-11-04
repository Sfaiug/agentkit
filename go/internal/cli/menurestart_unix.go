//go:build linux || darwin

package cli

import "syscall"

func execMenu(program string, args, env []string) error {
	return syscall.Exec(program, args, env)
}
