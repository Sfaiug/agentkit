package cli

import (
	"os"
	"os/exec"
)

func execMenu(program string, args, env []string) error {
	cmd := exec.Command(program, args[1:]...)
	cmd.Env, cmd.Stdin, cmd.Stdout, cmd.Stderr = env, os.Stdin, os.Stdout, os.Stderr
	if err := cmd.Run(); err != nil {
		if _, exited := err.(*exec.ExitError); !exited {
			return err
		}
	}
	os.Exit(cmd.ProcessState.ExitCode())
	return nil
}
