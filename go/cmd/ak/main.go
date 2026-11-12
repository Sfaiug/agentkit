package main

import (
	"os"

	"agentkit/internal/box"
	"agentkit/internal/cli"
	"agentkit/internal/host"
	"agentkit/internal/launch"
	"agentkit/internal/localtime"
)

func main() {
	host.Placed()
	localtime.Read()
	if code, first := box.First(); first {
		os.Exit(code)
	}
	if code, waiting := launch.Waiter(); waiting {
		os.Exit(code)
	}
	os.Exit(cli.Main(os.Args[1:], os.Stdout, os.Stderr))
}
