package googlecloud

import (
	"cmp"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"slices"
)

// unanswered is why Google did not answer this process at all, once it has not: each later call
// fails in the same words, asking nothing, so a process waits out one timeout, no more.
var unanswered error

// failure is a call failing, in plain words: where Google did not answer at all, with no
// connection, a timeout, or a connection closed before any reply, every later call's too; a reply
// it gave, cut short or malformed, fails this call alone.
func failure(err error) error {
	var asked *url.Error
	if errors.As(err, &asked) {
		err = asked.Err
	}
	said := fmt.Errorf("asking Google failed: %w", err)
	var dropped *net.OpError
	var late net.Error
	if errors.As(err, &dropped) || errors.As(err, &late) && late.Timeout() || errors.Is(err, io.EOF) {
		unanswered = said
	}
	return said
}

// A refusal is Google refusing a request: its HTTP status, the reason it gives, and under 500,
// where it did nothing of the request, its own codes for why.
type refusal struct {
	status int
	reason string
	codes  []string
}

func (r *refusal) Error() string { return "Google refused: " + r.reason }

// codes is Google's codes in an operation or a refusal's body: each of its errors' code, else its
// reason, sorted; none in a body of no such errors.
func codes(body []byte) []string {
	var answer struct {
		Error struct {
			Errors []struct{ Code, Reason string }
		}
	}
	json.Unmarshal(body, &answer) // what it cannot read holds no code
	var found []string
	for _, one := range answer.Error.Errors {
		if code := cmp.Or(one.Code, one.Reason); code != "" {
			found = append(found, code)
		}
	}
	slices.Sort(found)
	return slices.Compact(found)
}

// gone is err, but none where Google no longer has what it was asked about (404): it is gone
// already.
func gone(err error) error {
	var refused *refusal
	if errors.As(err, &refused) && refused.status == http.StatusNotFound {
		return nil
	}
	return err
}
