package browser

import (
	"bytes"
	"os"
	"path/filepath"
	"testing"
)

// x11vnc's file for a password is the 8 bytes libvncserver's rfbEncryptAndStorePasswd wrote for
// it, read out once through Python's ctypes.
func TestAMintedPasswordIsWhatLibvncserverWrites(t *testing.T) {
	home := t.TempDir()
	t.Setenv("HOME", home)
	t.Setenv("USERPROFILE", home)
	path := filepath.Join(home, ".agentkit", "secrets", rfbauth)
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		t.Fatal(err)
	}
	sealed, err := vncauth("Kq7mW2xRt9Lp4ZaB")
	if err != nil {
		t.Fatal(err)
	}
	if err := keep(rfbauth, sealed); err != nil {
		t.Fatal(err)
	}
	written, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if want := []byte{0x66, 0x11, 0xbc, 0x6f, 0x46, 0x77, 0x84, 0xac}; !bytes.Equal(written, want) {
		t.Fatalf("wrote % x, libvncserver writes % x", written, want)
	}
}
