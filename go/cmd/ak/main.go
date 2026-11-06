package main

import (
	"fmt"
	"os"

	"agentkit/internal/box"
	"agentkit/internal/cli"
	"agentkit/internal/localtime"
)

func main() {
	if code, first := box.First(); first {
		os.Exit(code)
	}
	if !localtime.Read() {
		fmt.Fprintf(os.Stderr, "ak: TZ=%s: not implemented in Go yet\n", os.Getenv("TZ"))
		os.Exit(3)
	}
	os.Exit(cli.Main(os.Args[1:], os.Stdout, os.Stderr))
}
