package seat

import "time"

// CardLogin is the seat's word as its card takes it, and since when, where that word is the tick's
// news of a login, which CardAnswer leaves out: its card is the one the watcher's alert sent
// (notify.Turned).  "" for any other word.
func CardLogin(name string) (string, any) {
	now := time.Now()
	home, known := seated(now)
	if !known {
		return "", nil
	}
	word, _, since, login := home.cardAnswer(name, now)
	if !login {
		return "", nil
	}
	return word, since
}
