package notify

// AnswersRead is whether what the owner writes in that seat's conversation is Go's to read, with no
// card's retirement deferred to its Python pass: Go then answers by that conversation as
// notify.answer_written does, none of the messages it reads holding a card's reply.
func AnswersRead(name string) bool {
	_, err := OwnerSaid(name)
	return err == nil && retirementsDrained()
}

// QuestionRead is whether the seat's own question stands, dated, where Go reads its answer in the
// conversation, there or not yet.
func QuestionRead(name string) bool {
	notice := Last(name)
	if !OwnerQuestion(notice) {
		return false
	}
	_, dated := finite(notice.Get("time"))
	return dated && AnswersRead(name)
}
