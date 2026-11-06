package harness

import (
	"bufio"
	"bytes"
	"crypto/rand"
	"crypto/sha1"
	"encoding/base64"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"path/filepath"
	"strconv"
	"time"

	"agentkit/internal/run"
)

// A codexClient talks to a seat's app server over the socket its launch writes down, as codex.py's
// Client does: JSON-RPC in WebSocket frames, its HTTP upgrade and masking included.
type codexClient struct {
	conn   net.Conn
	read   *bufio.Reader
	serial int
}

func codexDial(socket string) (*codexClient, error) {
	conn, err := net.DialTimeout("unix", socket, 15*time.Second)
	if err != nil {
		return nil, err
	}
	client := &codexClient{conn: conn, read: bufio.NewReader(conn)}
	var nonce [16]byte
	rand.Read(nonce[:])
	key := base64.StdEncoding.EncodeToString(nonce[:])
	conn.SetDeadline(time.Now().Add(15 * time.Second))
	_, err = fmt.Fprintf(conn, "GET / HTTP/1.1\r\nHost: localhost\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"+
		"Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n", key)
	var head []byte
	for err == nil && !bytes.HasSuffix(head, []byte("\r\n\r\n")) && len(head) <= 65536 {
		var line []byte
		line, err = client.read.ReadSlice('\n')
		head = append(head, line...)
	}
	accept := sha1.Sum([]byte(key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"))
	if err == nil && (!bytes.HasPrefix(head, []byte("HTTP/1.1 101 ")) ||
		!bytes.Contains(head, []byte(base64.StdEncoding.EncodeToString(accept[:])))) {
		err = errors.New("Codex socket did not accept WebSocket upgrade")
	}
	if err == nil {
		_, err = client.call("initialize", map[string]any{"clientInfo": map[string]any{"name": "agentkit", "version": "1"},
			"capabilities": map[string]any{"experimentalApi": true}})
	}
	if err == nil {
		err = client.send(map[string]any{"method": "initialized"})
	}
	if err != nil {
		conn.Close()
		return nil, err
	}
	return client, nil
}

// send writes one masked text frame, as a client must.
func (client *codexClient) send(value any) error {
	data, err := json.Marshal(value)
	if err != nil {
		return err
	}
	frame := []byte{0x81}
	switch size := len(data); {
	case size < 126:
		frame = append(frame, 0x80|byte(size))
	case size < 1<<16:
		frame = binary.BigEndian.AppendUint16(append(frame, 0x80|126), uint16(size))
	default:
		frame = binary.BigEndian.AppendUint64(append(frame, 0x80|127), uint64(size))
	}
	var mask [4]byte
	rand.Read(mask[:])
	frame = append(frame, mask[:]...)
	for i, b := range data {
		frame = append(frame, b^mask[i%4])
	}
	_, err = client.conn.Write(frame)
	return err
}

// receive is the next message the server sends, its fragments joined, a ping answered on the way.
func (client *codexClient) receive() (map[string]json.RawMessage, error) {
	var message []byte
	for {
		var head [2]byte
		if _, err := io.ReadFull(client.read, head[:]); err != nil {
			return nil, err
		}
		size := uint64(head[1] & 127)
		if size >= 126 {
			extended := make([]byte, 2)
			if size == 127 {
				extended = make([]byte, 8)
			}
			if _, err := io.ReadFull(client.read, extended); err != nil {
				return nil, err
			}
			size = 0
			for _, b := range extended {
				size = size<<8 | uint64(b)
			}
		}
		if head[1]&128 != 0 || size+uint64(len(message)) > 16<<20 {
			return nil, errors.New("Invalid Codex WebSocket frame")
		}
		data := make([]byte, size)
		if _, err := io.ReadFull(client.read, data); err != nil {
			return nil, err
		}
		switch head[0] & 15 {
		case 8:
			return nil, errors.New("Codex app server closed its connection")
		case 9:
			client.conn.Write(append([]byte{0x8a, 0x80}, 0, 0, 0, 0)) // a pong, masked by zeros
		case 0, 1:
			message = append(message, data...)
			if head[0]&128 != 0 {
				var read map[string]json.RawMessage
				return read, json.Unmarshal(message, &read)
			}
		}
	}
}

// call is the result of one request, within 15 seconds; what the server sends between is passed by.
func (client *codexClient) call(method string, params any) (json.RawMessage, error) {
	client.serial++
	if err := client.send(map[string]any{"id": client.serial, "method": method, "params": params}); err != nil {
		return nil, err
	}
	client.conn.SetDeadline(time.Now().Add(15 * time.Second))
	for {
		message, err := client.receive()
		if err != nil {
			return nil, err
		}
		if string(message["id"]) != strconv.Itoa(client.serial) {
			continue
		}
		if failure, failed := message["error"]; failed {
			var said struct{ Message string }
			json.Unmarshal(failure, &said)
			return nil, errors.New(said.Message)
		}
		return message["result"], nil
	}
}

// codexInFlight is the background work the seat's thread still runs, in the shape Claude Code hands
// its Stop hook, as codex.py `in_flight` reads it from the seat's own app server, the one place
// 0.163 lists it: its background terminals and the sub-agents it spawned, at any depth, still
// working.  0.163 wakes the seat for neither once it ends, so each is a `terminal` or an `agent`,
// held and never waited on.  False where the server cannot say: unread work is no evidence of none.
func codexInFlight(thread string) ([]any, bool) {
	data, err := os.ReadFile(filepath.Join(codexHome(os.Environ()), "connection.json"))
	var connection struct{ Socket string }
	if err != nil || json.Unmarshal(data, &connection) != nil || thread == "" {
		return nil, false
	}
	client, err := codexDial(connection.Socket)
	if err != nil {
		return nil, false
	}
	defer client.conn.Close()
	terminals, read := codexPages(client, "thread/backgroundTerminals/list", map[string]any{"threadId": thread})
	agents, listed := codexPages(client, "thread/list", map[string]any{"ancestorThreadId": thread, "sourceKinds": []string{"subAgentThreadSpawn"}})
	if !read || !listed {
		return nil, false
	}
	tasks := []any{}
	for _, each := range terminals {
		tasks = append(tasks, run.Fields("id", each.Get("processId"), "type", "terminal", "status", "running", "description", each.Get("command")))
	}
	for _, each := range agents {
		if status := each.Dict("status"); status != nil && status.Str("type") == "active" {
			named := each.Get("agentNickname")
			if !each.Truthy("agentNickname") {
				named = each.Get("preview")
			}
			tasks = append(tasks, run.Fields("id", each.Get("id"), "type", "agent", "status", "running", "description", named))
		}
	}
	return tasks, true
}

// codexPages is every item of a listing, page by page, and whether each page could be read.
func codexPages(client *codexClient, method string, params map[string]any) (found []*run.Object, ok bool) {
	var cursor any
	for {
		params["cursor"] = cursor
		result, err := client.call(method, params)
		read, _ := run.Decode(result)
		page, _ := read.(*run.Object)
		if err != nil || page == nil {
			return nil, false
		}
		for _, item := range page.List("data") {
			if item, isObject := item.(*run.Object); isObject {
				found = append(found, item)
			}
		}
		if !page.Truthy("nextCursor") {
			return found, true
		}
		cursor = page.Get("nextCursor")
	}
}
