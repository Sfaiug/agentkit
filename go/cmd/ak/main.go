package main

import (
	"os"

	"agentkit/internal/box"
	"agentkit/internal/cli"
)

func main() {
	if code, first := box.First(); first {
		os.Exit(code)
	}
	os.Exit(cli.Main(os.Args[1:], os.Stdout, os.Stderr))
}
