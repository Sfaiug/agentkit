package cli

import "os"

// Nothing crosses a restart on Windows, where the menu leaves the terminal to Python.
func cross(string, []byte) []string { return nil }

func crossed(variable string) []byte {
	os.Unsetenv(variable)
	return nil
}
