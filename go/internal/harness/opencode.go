package harness

func init() {
	plugins["opencode"] = plugin{mode: opencodeMode, seats: true, looks: true,
		record: opencodeRecord, keys: []string{"opencode_launch"}, kept: opencodeKept, forget: receiptGone("opencode"),
		owned: opencodeConversation, launched: opencodeLaunched, retire: receiptRetired("opencode")}
}
