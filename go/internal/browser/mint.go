package browser

import (
	"cmp"
	"crypto/des"
	"crypto/rand"
	"errors"
	"io"
	"math/big"
	"math/bits"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"slices"

	"agentkit/internal/config"
)

// rfbauth is x11vnc's own password file in ak's secrets, which no password can be read back out of.
const rfbauth = "browser-bridge-vnc.rfbauth"

// alphabet is what Python's browser.mint draws each of a password's 16 characters from.
const alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

// mint is `ak browser login` where no password can be read, as Python's browser.login and mint
// do it: a new password, kept as text and as x11vnc's file, with x11vnc alone restarted onto it,
// since Chromium's profile is the logins.  Everything that leaves it to Python is asked before a
// line is printed or a file written.
func mint(out io.Writer, address string) (int, error) {
	if !libvncserver() {
		return 0, ErrPython // Python's mint writes the text, then refuses
	}
	env, err := config.ChildEnv()
	if err != nil {
		return 0, ErrPython
	}
	restart := false
	if onPath("systemctl") {
		states, err := unitStates(env)
		if err != nil {
			return 0, err
		}
		restart = states[slices.Index(units, x11vncUnit)] != "absent"
	}
	password := ""
	for range 16 {
		n, err := rand.Int(rand.Reader, big.NewInt(int64(len(alphabet))))
		if err != nil {
			return 0, err
		}
		password += string(alphabet[n.Int64()])
	}
	sealed, err := vncauth(password)
	if err != nil {
		return 0, ErrPython // Python's libvncserver encrypts where Go's DES is refused
	}
	if config.EnsureDirs() != nil {
		return 0, ErrPython // undone, for Python to fail on as it does
	}
	if _, err := os.Stat(filepath.Join(config.Home(), "secrets", rfbauth)); err == nil &&
		!show(out, rfbauth+" is here but the plaintext is not, and it cannot be read back out; minting a new password") {
		return 0, nil
	}
	if err := keep(passwords[0], []byte(password+"\n")); err != nil {
		return 0, err
	}
	if err := keep(rfbauth, sealed); err != nil {
		return 0, err
	}
	if restart {
		if code, _, err := systemctl(env, true, "restart", x11vncUnit); err != nil {
			return 0, err
		} else if code != 0 {
			return 0, errors.New("wrote a new VNC password but could not restart " + x11vncUnit + "; the old password is still live")
		}
		if !show(out, "x11vnc restarted onto a new password; Chromium and its tabs were not touched") {
			return 0, nil
		}
	}
	signIn(out, address, password)
	return 0, nil
}

// libvncserver is whether `/sbin/ldconfig -p` lists it for this program's ABI, the first place
// Python's ctypes.util.find_library looks, and reads as it does.
func libvncserver() bool {
	abi := map[string]string{"amd64": "libc6,x86-64", "ppc64": "libc6,64bit", "s390x": "libc6,64bit"}[runtime.GOARCH]
	ldconfig := exec.Command("/sbin/ldconfig", "-p")
	ldconfig.Env = []string{"LC_ALL=C", "LANG=C"}
	listed, _ := ldconfig.Output() // what it printed counts, however it exited
	return regexp.MustCompile(`\s+libvncserver\.\S+\s+\(` + regexp.QuoteMeta(cmp.Or(abi, "libc6"))).Match(listed)
}

// vncauth is x11vnc's file for password, libvncserver's rfbEncryptAndStorePasswd's 8 bytes: the
// password's first 8, NUL-padded, DES-encrypted under libvncserver's fixed key.  Written here, the
// password is on no command line, as it would be given to `x11vnc -storepasswd`.
func vncauth(password string) ([]byte, error) {
	key := []byte{23, 82, 107, 6, 35, 78, 88, 7}
	for i := range key {
		key[i] = bits.Reverse8(key[i]) // libvncserver's DES reads each key byte lowest bit first
	}
	block, err := des.NewCipher(key)
	if err != nil {
		return nil, err // DES refused outright, as under GODEBUG=fips140=only
	}
	sealed := make([]byte, 8)
	copy(sealed, password)
	block.Encrypt(sealed, sealed)
	return sealed, nil
}

// keep puts data in the named secret as Python's browser.mint does: written owner-only beside
// it as NAME.tmp, then renamed over it, so a write cut short leaves the one before.
func keep(name string, data []byte) error {
	path := filepath.Join(config.Home(), "secrets", name)
	temp := path + ".tmp"
	defer os.Remove(temp) // nothing once renamed; a write that failed leaves no password behind
	if err := os.WriteFile(temp, data, 0o600); err != nil {
		return err
	}
	if err := os.Chmod(temp, 0o600); err != nil { // one left there before is owner-only too
		return err
	}
	return os.Rename(temp, path)
}
