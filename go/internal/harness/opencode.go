package harness

// OpenCode's own opencode.json says whether a MiMo model runs on a token plan or is paid by the
// token (agentkit/harness/opencode.py's `mode`).
func init() {
	plugins["opencode"] = plugin{paysItsOwnWay: true, seats: true, looks: true,
		record: opencodeRecord, keys: []string{"opencode_launch"}, kept: opencodeKept, forget: receiptGone("opencode")}
}
