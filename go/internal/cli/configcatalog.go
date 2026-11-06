package cli

import (
	"context"
	"time"

	modelListing "agentkit/internal/listing"
	"agentkit/internal/menu"
	"agentkit/internal/motion"
	"agentkit/internal/terminal"
)

func waitingConfigCatalog(keyboard *terminal.Keyboard, painter *terminal.Painter, cells []menu.Cell) configCatalog {
	return configCatalog{ask: func(harness string) ([]modelListing.Choice, error) {
		return waitConfigCatalog(harness, "config", cells, keyboard, painter)
	}}
}

func waitConfigCatalog(harness, title string, cells []menu.Cell, keyboard *terminal.Keyboard, painter *terminal.Painter) ([]modelListing.Choice, error) {
	return waitAdapter(title, cells, keyboard, painter, func(ctx context.Context) ([]modelListing.Choice, error) {
		return modelListing.ChoicesContext(ctx, harness)
	})
}

// waitAdapter is what ask answers, the frame up while an adapter is asked.  The UI owns every draw;
// the adapter owns only its answer. Esc cancels and reaps it.
func waitAdapter[T any](title string, cells []menu.Cell, keyboard *terminal.Keyboard, painter *terminal.Painter, ask func(context.Context) (T, error)) (T, error) {
	var none T
	ctx, cancel := context.WithCancel(context.Background())
	clock := &motion.Clock{}
	frame := time.AfterFunc(time.Hour, keyboard.Wake)
	defer frame.Stop()
	draw := func() {
		screen := keyboard.Screen()
		clock.Draw(time.Now())
		painter.Write(menu.CatalogWaiting(screen, title, time.Now().Format("15:04"), cells, clock), screen)
		if next, due := clock.Next(); due {
			frame.Reset(next)
		} else {
			frame.Stop()
		}
	}
	draw() // the frame is visible before an adapter can block
	type answer struct {
		value T
		err   error
	}
	result, ended := make(chan answer, 1), make(chan struct{})
	go func() {
		defer close(ended)
		value, err := ask(ctx)
		result <- answer{value, err}
		keyboard.Wake()
	}()
	defer func() { cancel(); <-ended }()
	var typed []terminal.Key // for the screen the catalog opens
	for {
		select {
		case got := <-result:
			keyboard.Unread(typed...)
			return got.value, got.err
		default:
		}
		key := keyboard.ReadKey()
		switch key.Name {
		case "esc", "eof":
			return none, context.Canceled
		case "again":
			painter.Forget()
		case "wake":
		default:
			typed = append(typed, key)
		}
		draw()
	}
}
