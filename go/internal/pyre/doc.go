// Package pyre will compile the patterns harness manifests write in Python's re syntax, on the
// backtracking engine vendored beside it: Go's own regexp has no lookaround or backreference.
package pyre

import _ "github.com/dlclark/regexp2"
