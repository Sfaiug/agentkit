package harness

func init() {
	plugins["opencode"] = plugin{mode: opencodeMode, seats: true, looks: true,
		record: opencodeRecord, owned: opencodeConversation, keys: []string{"opencode_launch"}, kept: opencodeKept, forget: receiptGone("opencode")}
}
