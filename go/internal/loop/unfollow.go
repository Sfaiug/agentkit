package loop

import "time"

// Unfollow waits until a foreground `ak run` following a driver just ended has looked at its record
// again: Follow reads it once a followEvery and follows on to a successor named sooner, where
// Python's foreground run ends with its loop.
func Unfollow() { time.Sleep(5 * followEvery) }
