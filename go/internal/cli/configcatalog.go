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

// The UI owns every draw; the adapter owns only its answer. Esc cancels and reaps it.
func waitConfigCatalog(harness, title string, cells []menu.Cell, keyboard *terminal.Keyboard, painter *terminal.Painter) ([]modelListing.Choice, error) {
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
		choices []modelListing.Choice
		err     error
	}
	result, ended := make(chan answer, 1), make(chan struct{})
	go func() {
		defer close(ended)
		choices, err := modelListing.ChoicesContext(ctx, harness)
		result <- answer{choices, err}
		keyboard.Wake()
	}()
	defer func() { cancel(); <-ended }()
	var typed []terminal.Key // for the screen the catalog opens
	for {
		select {
		case got := <-result:
			keyboard.Unread(typed...)
			return got.choices, got.err
		default:
		}
		key := keyboard.ReadKey()
		switch key.Name {
		case "esc", "eof":
			return nil, context.Canceled
		case "again":
			painter.Forget()
		case "wake":
		default:
			typed = append(typed, key)
		}
		draw()
	}
}
