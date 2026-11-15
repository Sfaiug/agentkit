package harness

func init() {
	plugins["opencode"] = plugin{mode: opencodeMode, seats: true, looks: true,
		record: opencodeRecord, keys: []string{"opencode_launch"}, forget: receiptGone("opencode"),
		owned: opencodeConversation, found: opencodeNamed, named: opencodeNamed, said: opencodeSaid, typed: byName(opencodeTyped), answered: opencodeAnswered, launched: opencodeLaunched, retire: receiptRetired("opencode"),
		switchable: opencodeSwitchable, follows: opencodeFollows}
}
