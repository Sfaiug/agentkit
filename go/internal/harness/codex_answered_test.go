package harness

import (
	"encoding/json"
	"testing"
)

// TestCodexCardAnswersAreTextAndNotBlank: an answer on a Codex card counts only where its question,
// every label and description, and the answer itself are text, and the answer is not blank, as
// Python's Harness.answers keeps them.
func TestCodexCardAnswersAreTextAndNotBlank(t *testing.T) {
	token, write := codexSeat(t)
	encoded := func(value any) string {
		data, _ := json.Marshal(value)
		return string(data)
	}
	called := func(tool, call string, questions []any) string {
		return encoded(map[string]any{"type": "response_item", "payload": map[string]any{"type": "function_call",
			"name": tool, "call_id": call, "arguments": encoded(map[string]any{"questions": questions})}}) + "\n"
	}
	plan := func(question, label, description any, words []any) string {
		option := map[string]any{"label": label, "description": description}
		asked := called(codexPlanTool, "p1", []any{map[string]any{"id": "q", "question": question, "options": []any{option}}})
		output := encoded(map[string]any{"answers": map[string]any{"q": map[string]any{"answers": words}}})
		return asked + encoded(map[string]any{"type": "response_item", "timestamp": "2026-11-05T10:00:02Z",
			"payload": map[string]any{"type": "function_call_output", "call_id": "p1", "output": output}}) + "\n"
	}
	async := func(title, option any) string {
		reply := codexReply + encoded([]any{map[string]any{"questionItemId": encoded([]any{codexCardTool, "c1", 0}),
			"answer": "Blue"}}) + codexReplyEnd
		return called(codexCardTool, "c1", []any{map[string]any{"title": title, "options": []any{option}}}) +
			encoded(map[string]any{"type": "event_msg", "timestamp": "2026-11-05T10:00:03Z", "payload": map[string]any{
				"type": "item_completed", "item": map[string]any{"type": "UserMessage",
					"content": []any{map[string]any{"type": "text", "text": reply}}}}}) + "\n"
	}
	for _, each := range []struct {
		name, rollout, answer string
	}{
		{"a plan card's pick", plan("Which colour?", "Blue", "the sky's", []any{"Blue", "user_note: and soon"}), "Blue\nand soon"},
		{"a plan card's answer with no words", plan("Which colour?", "Blue", "", []any{}), ""},
		{"a plan card's blank answer", plan("Which colour?", "Blue", "", []any{""}), ""},
		{"a plan card's answer of space", plan("Which colour?", "Blue", "", []any{" \t"}), ""},
		{"a plan card's empty note", plan("Which colour?", "Blue", "", []any{"user_note: "}), ""},
		{"a plan card asking nothing", plan(nil, "Blue", "", []any{"Blue"}), ""},
		{"a plan card's label of no text", plan("Which colour?", 42, "", []any{"Blue"}), ""},
		{"a plan card's description of no text", plan("Which colour?", "Blue", 42, []any{"Blue"}), ""},
		{"a plan card's description of null", plan("Which colour?", "Blue", nil, []any{"Blue"}), ""},
		{"an async card's reply", async("Which colour?", "Blue"), "Blue"},
		{"an async card asking nothing", async(nil, "Blue"), ""},
		{"an async card's option of no text", async("Which colour?", 42), ""},
	} {
		write(each.rollout)
		_, cards, err := codexAnswered(map[string]any{codexLaunch: token})
		if err != nil || each.answer == "" && len(cards) != 0 ||
			each.answer != "" && (len(cards) != 1 || cards[0].Answer != each.answer || cards[0].Question != "Which colour?") {
			t.Errorf("%s: %#v, %v", each.name, cards, err)
		}
	}
}
