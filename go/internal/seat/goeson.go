package seat

import (
	"os"
	"time"

	"agentkit/internal/config"
	"agentkit/internal/harness"
	"agentkit/internal/host"
	"agentkit/internal/run"
	script "agentkit/internal/transcript"
)

// goesOn is what the seat's relaunch tells it its end cut off, and whether Go carries that
// relaunch.  orch.reopen, the owner's and a harness's end's, tells it: owing's line, read before the relaunch
// moves the hook facts aside, the line its harness opens on where its own conversation comes back;
// nothing where the owner stopped or closed it, which ended on purpose.  Any other relaunch tells
// nothing and leaves Python a seat cut off (cutOff), whose revival tells it so; a dry run tells
// nobody anything.
func (seat *reopening) goesOn(how How) (string, bool) {
	file, _ := run.ReadJSON(seatFile(seat.name))
	own := seat.model.Harness
	if !how.Owner || how.DryRun {
		return "", how.DryRun && !how.Detached || !cutOff(seat.name, own, file)
	}
	if file != nil && (file.Truthy("stopped_at") || file.Truthy("closed_by_owner")) {
		return "", true
	}
	cut, known := Seat{Name: seat.name, own: own, reader: harness.For(own)}.owing()
	if seat.conversation != "" && seat.opened {
		seat.line = cut.line
	}
	return cut.line, known
}

// goOn has the seat, relaunched at that moment and going by that name now, go on with the line
// its end cut off: its first prompt where its conversation came back (relaunched), else owed,
// saying it was started fresh, for the tick to type (watch.owe_line).
func (seat reopening) goOn(name, line string, at float64) error {
	switch {
	case line == "":
		return nil
	case seat.line != "":
		return relaunched(name, seat.model.Harness, line, at, host.BootID())
	}
	return OweLine(name, line+freshContinue)
}

// relaunched marks the line a seat relaunched at that moment goes on with, for continue_turns
// (watch.relaunched): where its harness took it as its first prompt the mark only waits for that
// prompt, and elsewhere the tick types it once the harness is listening.
func relaunched(name, own, line string, at float64, boot string) error {
	mark := run.Fields("boot", boot, "at", run.Float(at), "name", name, "line", line)
	if takesFirstPrompt(own) {
		mark.Set("launched", true)
	}
	return Write(name, "midturn", mark)
}

// takesFirstPrompt is whether that harness opens on a first prompt its adapter puts on the command
// line (orch.takes_line).
func takesFirstPrompt(own string) bool {
	launch, _ := config.Section(own, "launch")
	return launch["first_prompt"] == true
}

// receipted writes down the line the harness opens on as ak's, before it is up, where it takes
// one as its first prompt (orch.launch): the owner's messages, a question's answer among them,
// leave it out.  A launch that then fails leaves it, which can only ever match that line of ak's.
func (seat reopening) receipted(name string) error {
	if seat.line == "" || !takesFirstPrompt(seat.model.Harness) {
		return nil
	}
	_, record, err := config.ResolveSession(name)
	if err != nil {
		return err
	}
	file, err := os.OpenFile(ownFile("input", name), os.O_WRONLY|os.O_APPEND|os.O_CREATE, 0o666)
	if err != nil {
		return err
	}
	defer file.Close()
	_, err = file.WriteString(run.Line(typingReceipt(seat.model.Harness, record, seat.line)) + "\n")
	return err
}

// typingReceipt is the typing receipt a line of ak's is told by (Harness.receipt), written before it
// goes into the seat's conversation: the messages already there are `after` it, and where its
// harness names that conversation only later, its launch (harness.Launch) says which it is.
func typingReceipt(own string, record map[string]any, text string) *run.Object {
	conversation, prompts, _, _ := script.Typed(own, record, "")
	sent := run.Fields("at", run.Float(seconds(time.Now())), "text", text, "source", "ak", "harness", own,
		"conversation", conversation, "after", len(prompts))
	if conversation == nil {
		sent.Set("launch", harness.Launch(record))
	}
	return sent
}
