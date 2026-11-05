package harness

import (
	"crypto/rand"
	"encoding/hex"

	"agentkit/internal/run"
)

func antigravityLaunch() (*run.Object, []string) {
	token := make([]byte, 16)
	rand.Read(token)
	token[6], token[8] = token[6]&0x0f|0x40, token[8]&0x3f|0x80
	launch := hex.EncodeToString(token)
	return run.Fields("antigravity_launch", launch, "antigravity_open", nil),
		[]string{"AGENTKIT_ANTIGRAVITY_LAUNCH=" + launch}
}
