package cli

import (
	"context"
	"errors"
	"fmt"
	"io"

	"agentkit/internal/config"
)

// planCheck makes the done check a seat's finished plan owes, after its listing, and prints it as
// `ak orch check` does (plan.main): a gap is the seat's to build or its owner's to drop.
func planCheck(ctx context.Context, name string, out, errOut io.Writer) error {
	name, found, err := ownerGaps(ctx, name, errOut)
	if err == nil && told(out, name, found) {
		fmt.Fprintln(out, "Build what is missing, or ask your owner whether to drop it. Keep a picture of "+
			"each screen your work changed with `ak orch look FILE`, an image or a text capture of a "+
			"terminal screen.")
	}
	return err
}

// checkCarried is errLeft where Python makes seat current's done check (gaps), settled before the
// plan is ticked from what the check reads, nothing drawn or written: the owner's words, which
// plan's reader of whether the check is owed has read as strictly as Python's, the pictures
// (keptPictures) and runs (checkFiles) its workspace holds and the model that checks (checking).  Any other end is
// the check's own to say.
func checkCarried(current string) error {
	_, record, err := config.ResolveSession(current)
	if err != nil {
		return nil
	}
	if _, err := keptPictures(current); errors.Is(err, errLeft) {
		return err
	}
	if _, err := checkFiles(current, nil, nil, nil, nil); errors.Is(err, errLeft) {
		return err
	}
	if _, _, err := checking(record); errors.Is(err, errLeft) {
		return err
	}
	return nil
}
