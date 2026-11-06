package tick

import "agentkit/internal/browser"

// A test tick's browser tidy finds no browser: the host's holds other sessions' tabs, and its
// cap would close some of them.
func init() { browser.CDP = "http://127.0.0.1:0" }
