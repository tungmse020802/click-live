//go:build windows

package main

import (
	"bufio"
	"fmt"
	"os"
	"regexp"
	"strconv"
	"strings"
	"syscall"
	"time"
	"unsafe"
)

const (
	inputMouse           = 0
	mouseeventfLeftDown  = 0x0002
	mouseeventfLeftUp    = 0x0004
)

var (
	user32               = syscall.NewLazyDLL("user32.dll")
	procSetProcessDPIAware = user32.NewProc("SetProcessDPIAware")
	procSetCursorPos     = user32.NewProc("SetCursorPos")
	procGetCursorPos     = user32.NewProc("GetCursorPos")
	procSendInput        = user32.NewProc("SendInput")
	procGetDoubleClickTime = user32.NewProc("GetDoubleClickTime")
)

type point struct {
	X int32
	Y int32
}

type mouseInput struct {
	Dx          int32
	Dy          int32
	MouseData   uint32
	DwFlags     uint32
	Time        uint32
	DwExtraInfo uintptr
}

type input struct {
	Type uint32
	Pad  uint32
	Mi   mouseInput
}

var (
	clickRx = regexp.MustCompile(`^(\d+),(-?\d+),(-?\d+)$`)
	pingRx  = regexp.MustCompile(`^ping:(\d+)$`)
)

func envBool(name string, defaultVal bool) bool {
	v := strings.TrimSpace(strings.ToLower(os.Getenv(name)))
	if v == "" {
		return defaultVal
	}
	return v != "0" && v != "false" && v != "no"
}

func envInt(name string, defaultVal int) int {
	v := strings.TrimSpace(os.Getenv(name))
	if v == "" {
		return defaultVal
	}
	n, err := strconv.Atoi(v)
	if err != nil || n < 0 {
		return defaultVal
	}
	return n
}

func clickSettleMs() int  { return envInt("DESKTOP_CLICK_SETTLE_MS", 20) }
func clickStepMs() int   { return envInt("DESKTOP_CLICK_STEP_MS", 12) }

func doubleClickGapMs() int {
	if v := envInt("DESKTOP_CLICK_DOUBLE_GAP_MS", -1); v >= 0 {
		return v
	}
	ret, _, _ := procGetDoubleClickTime.Call()
	sys := int(ret)
	if sys > 0 {
		gap := sys / 3
		if gap < 40 {
			gap = 40
		}
		if gap > 180 {
			gap = 180
		}
		return gap
	}
	return 60
}

func isDoubleClickEnabled() bool {
	return envBool("DESKTOP_CLICK_DOUBLE", true)
}

func sleepMs(ms int) {
	if ms <= 0 {
		return
	}
	time.Sleep(time.Duration(ms) * time.Millisecond)
}

func sendMouseButton(down bool) (int, error) {
	flags := uint32(mouseeventfLeftUp)
	if down {
		flags = mouseeventfLeftDown
	}
	inp := input{
		Type: inputMouse,
		Mi: mouseInput{
			DwFlags: flags,
		},
	}
	ret, _, err := procSendInput.Call(
		1,
		uintptr(unsafe.Pointer(&inp)),
		unsafe.Sizeof(inp),
	)
	if ret != 1 {
		gle := syscall.GetLastError()
		if gle == 0 && err != syscall.Errno(0) {
			return int(ret), fmt.Errorf("sendinput-failed,gle=%v", err)
		}
		return int(ret), fmt.Errorf("sendinput-failed,gle=%d", gle)
	}
	return 1, nil
}

func performButtonClicks() error {
	sleepMs(clickSettleMs())
	if _, err := sendMouseButton(true); err != nil {
		return err
	}
	sleepMs(clickStepMs())
	if _, err := sendMouseButton(false); err != nil {
		return err
	}
	if !isDoubleClickEnabled() {
		return nil
	}
	sleepMs(doubleClickGapMs())
	if _, err := sendMouseButton(true); err != nil {
		return err
	}
	sleepMs(clickStepMs())
	_, err := sendMouseButton(false)
	return err
}

func clickAt(x, y int) (string, bool) {
	ok, _, _ := procSetCursorPos.Call(uintptr(x), uintptr(y))
	if ok == 0 {
		gle := syscall.GetLastError()
		return fmt.Sprintf("setcursorpos-failed,gle=%d", gle), false
	}

	if err := performButtonClicks(); err != nil {
		return err.Error(), false
	}

	var pt point
	ok, _, _ = procGetCursorPos.Call(uintptr(unsafe.Pointer(&pt)))
	if ok == 0 {
		return "getcursorpos-failed", false
	}
	if abs(int(pt.X)-x) > 3 || abs(int(pt.Y)-y) > 3 {
		return fmt.Sprintf("cursor-at:%d,%d", pt.X, pt.Y), false
	}
	return "", true
}

func abs(n int) int {
	if n < 0 {
		return -n
	}
	return n
}

func writeLine(w *bufio.Writer, line string) {
	fmt.Fprintln(w, line)
	w.Flush()
}

func main() {
	_, _, _ = procSetProcessDPIAware.Call()

	out := bufio.NewWriter(os.Stdout)
	writeLine(out, "ready")

	scanner := bufio.NewScanner(os.Stdin)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}
		if line == "quit" {
			break
		}
		if line == "ping" {
			writeLine(out, "pong")
			continue
		}
		if m := pingRx.FindStringSubmatch(line); m != nil {
			writeLine(out, "pong:"+m[1])
			continue
		}
		if m := clickRx.FindStringSubmatch(line); m != nil {
			id, _ := strconv.Atoi(m[1])
			x, _ := strconv.Atoi(m[2])
			y, _ := strconv.Atoi(m[3])
			if detail, ok := clickAt(x, y); ok {
				writeLine(out, fmt.Sprintf("ok:%d,%d,%d", id, x, y))
			} else {
				writeLine(out, fmt.Sprintf("err:%d,%s", id, detail))
			}
			continue
		}
		writeLine(out, "err")
	}
}
