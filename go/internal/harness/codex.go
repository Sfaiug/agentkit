package harness

// A Codex seat owns a conversation only by its launch receipt (codex.py `conversation`), which
// Go reads to tell its seat's word, to reopen it on, and to read its owner's words in.  What its
// thread runs in the background its own app server says (`holds`).
func init() {
	plugins["codex"] = plugin{seats: true, looks: true, recorded: codexError, answer: codexAnswer, owns: codexOwns, owned: codexOwned,
		found: codexFound, named: codexFound, typed: codexTyped, answered: codexAnswered, replies: codexReplies,
		record: codexRecord, reconcile: codexReconcile, keys: []string{codexLaunch, "codex_history"}, kept: codexKept,
		fresh: "starts a new Codex conversation", receipt: codexLaunch, registerMCP: codexRegisterMCP,
		launched: codexLaunched, retire: codexRetire, handed: codexHanded, moveReady: codexMoveReady, forget: codexForget,
		opens: true, interactive: codexInteractive, serve: codexServeSeat, hookEvent: codexHookEvent,
		tokens: codexTokens, tokenSources: codexTokenSources, tokenUsage: codexTokenUsage, yolo: codexYolo,
		rulebook: ".codex/AGENTS.md", holds: codexHolds, auth: codexAuth}
}
