package loop

// LoginKeys are what a login parks on a run, Python's: the harness it waits for, and the stamps
// that pace and release the tick's resume of it.  A run parked on no login holds none of them.
var LoginKeys = []string{"waiting_for", "login_resume_at", "login_back_at"}
