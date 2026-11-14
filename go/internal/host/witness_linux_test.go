package host

import (
	"os"
	"path/filepath"
	"testing"
)

// Work that cannot say it started where it was placed goes into its unit all the same, the
// witness saying so for it, and what it becomes does not inherit where that word goes.
func TestWitnessedWorkGoesIntoItsUnit(t *testing.T) {
	for name, systemdRun := range map[string]string{
		"a scope": `while [ "$1" != -- ]; do [ "$1" != --expand-environment=no ] || literal=yes; shift; done; shift
case "$*" in *'$'*) [ -n "$literal" ] || exit 1;; esac; exec "$@"`,
		"a service": `while [ "$1" != -- ]; do case $1 in --setenv=AK_PLACED=*) export AK_PLACED="${1#*=*=}";; esac; shift; done; shift
for word; do set -- "$@" "$(printf %s "$word" | sed 's/[$][$]/$/g')"; shift; done; "$@"; exit 1`,
	} {
		t.Run(name, func(t *testing.T) {
			log, ran, _ := placing(t, systemdRun, name == "a scope")
			work := filepath.Join(filepath.Dir(ran), "work")
			os.WriteFile(work, []byte(`#!/bin/sh
echo "${AK_PLACED:+inherited }$$" >>"$1"`), 0o755)
			pid, scope, reason, err := Place(Witnessed(work, ran), log, "agentkit-lander-acme-1", nil, true)
			if err != nil || scope != "agentkit-lander-acme-1" || pid != ranAs(t, ran) {
				t.Fatalf("pid %d, %q %q %v", pid, scope, reason, err)
			}
		})
	}
}
