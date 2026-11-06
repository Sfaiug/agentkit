package adapters

import (
	"context"
	"os"
	"os/exec"
	"slices"
	"strings"
	"time"

	"agentkit/internal/config"
)

// Fresh starts a conversation on the account supplied by the reopening seat.
func Fresh(model config.Model, env []string) ([]string, string, error) {
	conversation := uuid()
	line, told, err := command(model, env, []string{conversation, "new"}, nil)
	if !told {
		conversation = ""
	}
	return line, conversation, err
}

func commandAccount(env []string) string {
	account := ""
	for _, pair := range env {
		if value, found := strings.CutPrefix(pair, "AGENTKIT_ACCOUNT="); found {
			account = value
		}
	}
	return loginAccount(account)
}

func loginAccount(account string) string {
	if account == "default" {
		return ""
	}
	return account
}

// SeatAuth asks the adapter's seat login, on that subscription. Its exit code is the answer.
func SeatAuth(own, account string) bool {
	argv, err := answering(own)
	if err != nil {
		return false
	}
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, argv[0], slices.Concat(argv[1:], []string{"auth", "seat"})...)
	cmd.Env = append(os.Environ(), "AGENTKIT_ACCOUNT="+loginAccount(account))
	return cmd.Run() == nil
}
