package seat

import (
	"testing"

	"agentkit/internal/terminal"
)

// Each want is what agentkit/statusbar.py and menu.last_column write for the same seat, so a bar
// reads the same whichever program wrote it last.

func TestTheBarsFormatsAreStatusbarsOwn(t *testing.T) {
	one := "#{?#{e|<=:#{e|+:#{w:@ak_top},#{e|+:#{w:@ak_need},2}},#{client_width}},#[align=left]#{@ak_top} #[align=right]#{@ak_need},#{?#{e|<=:#{e|+:#{w:@ak_top1},#{e|+:#{w:@ak_need},2}},#{client_width}},#[align=left]#{@ak_top1} #[align=right]#{@ak_need},#{?#{e|<=:#{e|+:#{w:@ak_top2},#{e|+:#{w:@ak_need},2}},#{client_width}},#[align=left]#{@ak_top2} #[align=right]#{@ak_need},#{?#{e|<=:#{e|+:#{w:@ak_top},#{e|+:#{w:@ak_fold},2}},#{client_width}},#[align=left]#{@ak_top} #[align=right]#{@ak_fold},#{?#{e|<=:#{e|+:#{w:@ak_top1},#{e|+:#{w:@ak_fold},2}},#{client_width}},#[align=left]#{@ak_top1} #[align=right]#{@ak_fold},#{?#{e|<=:#{e|+:#{w:@ak_top2},#{e|+:#{w:@ak_fold},2}},#{client_width}},#[align=left]#{@ak_top2} #[align=right]#{@ak_fold},#[align=left]#{=/#{?#{e|>:#{e|-:#{client_width},#{e|+:#{w:@ak_fold},2}},0},#{e|-:#{client_width},#{e|+:#{w:@ak_fold},2}},1}/…:@ak_top2} #[align=right]#{@ak_fold}}}}}}}"
	two := "#[align=left]#{?#{e|<=:#{w:@ak_why},#{e|-:#{client_width},#{e|+:#{w:@ak_key},2}}},#{@ak_why},#{?#{e|<=:#{w:@ak_why1},#{e|-:#{client_width},#{e|+:#{w:@ak_key},2}}},#{@ak_why1},#{?#{e|<=:#{w:@ak_why2},#{e|-:#{client_width},#{e|+:#{w:@ak_key},2}}},#{@ak_why2},#{?#{e|<=:#{w:@ak_why3},#{e|-:#{client_width},#{e|+:#{w:@ak_key},2}}},#{@ak_why3},#{?#{e|<=:#{w:@ak_why4},#{e|-:#{client_width},#{e|+:#{w:@ak_key},2}}},#{@ak_why4},#{=/#{?#{e|>:#{e|-:#{client_width},#{e|+:#{w:@ak_key},2}},0},#{e|-:#{client_width},#{e|+:#{w:@ak_key},2}},1}/…:@ak_why4}}}}}} #[align=right]#{@ak_key}"
	if got := barLineOne(); got != one {
		t.Fatalf("line one:\n%s", got)
	}
	if got := barLineTwo(); got != two {
		t.Fatalf("line two:\n%s", got)
	}
}

func TestTheBarSaysWhatStatusbarSays(t *testing.T) {
	t.Setenv("LC_ALL", "C.UTF-8")
	screen := terminal.For(nil)
	needs := " #[fg=#3d2e00,bg=#f6c400,bold] ! needs you #[default]   #[bold]acme#[nobold]   #[fg=#6c7086]Opus 5.5#[default]   "
	done := " #[fg=#ffffff,bg=#007e46] ✓ done #[default]   #[bold]acme#[nobold]   #[fg=#6c7086]Opus 5.5#[default]   "
	idle := " #[fg=#ffffff,bg=#6c7086] ○ idle #[default]   #[bold]acme#[nobold]   #[fg=#6c7086]Opus 5.5#[default]"
	crew := "  #[fg=#6c7086]Opus 5.5 orchestrates, builds, reviews   Astra builds   Spark reviews#[default]"
	for _, each := range []struct {
		word, reason, why string
		done, total       int
		tops              [3]string
	}{
		{"needs you", "session #1 closed", "  session ##1 closed", 1, 3, [3]string{
			needs + "#[fg=#f6c400]━━━━━━━━━╸#[fg=#6c7086]───────────────────#[default] 1 of 3",
			needs + "#[fg=#f6c400]━━━━━╸#[fg=#6c7086]───────────#[default] 1 of 3",
			needs + "#[fg=#f6c400]━╸#[fg=#6c7086]───#[default] 1 of 3"}},
		{"done", "it shipped", crew, 3, 3, [3]string{
			done + "#[fg=#007e46]━━━━━━━━━━━━━━━━━━━━━━━━━━━━━#[default] 3 of 3",
			done + "#[fg=#007e46]━━━━━━━━━━━━━━━━━#[default] 3 of 3",
			done + "#[fg=#007e46]━━━━━#[default] 3 of 3"}},
		{"idle", "session closed: press 1 to reopen", crew, 1, 3, [3]string{idle, idle, idle}},
	} {
		seat := Seat{Name: "acme", Word: each.word, reason: each.reason}
		told := map[string]string{}
		for _, option := range seat.barOptions(screen, "Opus 5.5", []string{"Opus 5.5", "Astra"}, []string{"Opus 5.5", "Spark"}, each.done, each.total) {
			if option[0] != "=acme:" {
				t.Fatalf("%s told %s", each.word, option[0])
			}
			told[option[1]] = option[2]
		}
		for i, option := range barTops {
			if told[option] != each.tops[i] {
				t.Errorf("%s %s:\n%s\nwant\n%s", each.word, option, told[option], each.tops[i])
			}
		}
		for _, option := range barWhys {
			if told[option] != each.why {
				t.Errorf("%s %s: %q", each.word, option, told[option])
			}
		}
		if told[barKey] != "Ctrl-b m#[fg=#6c7086]  menu #[default]" || told["set-titles-string"] != "acme · "+each.word {
			t.Errorf("%s: key %q, title %q", each.word, told[barKey], told["set-titles-string"])
		}
	}
	seat := Seat{Name: "a#b%", Word: "idle"}
	options := seat.barOptions(screen, "", nil, nil, 0, 0)
	if last := options[len(options)-1]; last != [3]string{"=a#b%:", "set-titles-string", "a##b%% · idle"} {
		t.Errorf("the title is told last, as tmux reads it: %q", last)
	}
}

func TestTheRightEndCountsTheOtherSeatsThatNeedYou(t *testing.T) {
	hit := "#{?#{&&:#{e|>:#{e|-:#{client_width},#{mouse_x}},1},#{e|<=:#{e|-:#{client_width},#{mouse_x}},25}},$1,}"
	one := []barRow{{id: "$1", name: "a", word: "needs you"}, {id: "$2", name: "b", word: "idle"}}
	said, short, found := barOthers(one, "b")
	if said != "#[range=right]#[fg=#f6c400,bold]! 1 other seat needs you#[default]#[norange] " ||
		short != "#[range=right]#[fg=#f6c400,bold]! 1 needs you#[default]#[norange] " || found != hit {
		t.Errorf("%q %q %q", said, short, found)
	}
	said, short, found = barOthers(append(one, barRow{id: "$3", name: "c", word: "needs you"}), "b")
	if said != "#[range=right]#[fg=#f6c400,bold]! 2 other seats need you#[default]#[norange] " ||
		short != "#[range=right]#[fg=#f6c400,bold]! 2 need you#[default]#[norange] " || found != hit {
		t.Errorf("%q %q %q", said, short, found)
	}
	if said, short, found := barOthers(one, "a"); said != "" || short != "" || found != "" {
		t.Errorf("a seat counts itself: %q %q %q", said, short, found)
	}
}
