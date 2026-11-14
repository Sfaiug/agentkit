package harness

// claudeReadBy is the names that conversation's transcript is read by, in order (claude.py
// `read_by`): Claude's own, then ak's (`kept`), a link to the same file that stays once Claude's
// cleanup deleted its own; none where the record names no conversation or no checkout.
func claudeReadBy(record map[string]any) []string {
	own := claudeConversation(record)
	if own == "" {
		return nil
	}
	conversation, _ := record["conversation"].(string)
	return []string{own, claudeKept(conversation)}
}
