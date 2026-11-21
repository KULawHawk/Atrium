//go:build windows

package capture

// Screen text through Windows UI Automation, by raw COM calls (no cgo, no extra
// module). UNTESTED ON A PC: the vtable positions below follow UIAutomationClient.h
// and are proved only by PC test T-10. Screen text is off by default
// (screen_text_seconds = 0) until T-10 passes, because a wrong position here would
// crash the session part (the service restarts it and logs each exit).

import (
	"errors"
	"fmt"
	"runtime"
	"strings"
	"syscall"
	"unsafe"

	"golang.org/x/sys/windows"
)

var (
	ole32              = windows.NewLazySystemDLL("ole32.dll")
	oleaut32           = windows.NewLazySystemDLL("oleaut32.dll")
	pCoInitializeEx    = ole32.NewProc("CoInitializeEx")
	pCoUninitialize    = ole32.NewProc("CoUninitialize")
	pCoCreateInstance  = ole32.NewProc("CoCreateInstance")
	pSysFreeString     = oleaut32.NewProc("SysFreeString")
	clsidCUIAutomation = windows.GUID{Data1: 0xff48dba4, Data2: 0x60ef, Data3: 0x4201, Data4: [8]byte{0xaa, 0x87, 0x54, 0x10, 0x3e, 0xef, 0x59, 0x4e}}
	iidIUIAutomation   = windows.GUID{Data1: 0x30cbe57d, Data2: 0xd9d0, Data3: 0x452a, Data4: [8]byte{0xab, 0x13, 0x7a, 0xc5, 0xac, 0x48, 0x25, 0xee}}
	iidIUIATextPattern = windows.GUID{Data1: 0x32eba289, Data2: 0x3583, Data3: 0x42c9, Data4: [8]byte{0x9c, 0x59, 0x3b, 0x6d, 0x9a, 0x1e, 0x9b, 0x6a}}
	errNoFrontWindow   = errors.New("no front window")
)

// vtable positions (IUnknown is 0..2).
const (
	vRelease = 2
	// IUIAutomation
	vElementFromHandle   = 6
	vCreateTrueCondition = 21
	// IUIAutomationElement
	vFindAll             = 6
	vGetCurrentPatternAs = 14
	vGetCurrentName      = 23
	// IUIAutomationElementArray
	vArrLength = 3
	vArrGet    = 4
	// IUIAutomationTextPattern
	vDocumentRange = 7
	// IUIAutomationTextRange
	vGetText = 12

	treeScopeDescendants = 4
	uiaTextPatternID     = 10014
	maxElements          = 400
	maxTextChars         = 20000
	clsctxInprocServer   = 1
	coinitMultithreaded  = 0
	rpcEChangedMode      = 0x80010106
)

// vcall calls method idx of a COM object.
func vcall(obj unsafe.Pointer, idx int, args ...uintptr) uintptr {
	vtbl := *(*unsafe.Pointer)(obj)
	fn := *(*uintptr)(unsafe.Add(vtbl, idx*int(unsafe.Sizeof(uintptr(0)))))
	r, _, _ := syscall.SyscallN(fn, append([]uintptr{uintptr(obj)}, args...)...)
	return r
}

func release(obj unsafe.Pointer) {
	if obj != nil {
		vcall(obj, vRelease)
	}
}

func out(p *unsafe.Pointer) uintptr { return uintptr(unsafe.Pointer(p)) }

func bstr(b *uint16) string {
	if b == nil {
		return ""
	}
	s := windows.UTF16PtrToString(b)
	pSysFreeString.Call(uintptr(unsafe.Pointer(b)))
	return s
}

func hr(r uintptr, what string) error {
	if int32(r) < 0 {
		return fmt.Errorf("%s failed (0x%08x)", what, uint32(r))
	}
	return nil
}

// ScreenText returns the front window's visible text: the names of its parts,
// then the text of any document area (consoles, editors), last lines kept.
func (Win) ScreenText() ([]string, error) {
	runtime.LockOSThread()
	defer runtime.UnlockOSThread()
	if r, _, _ := pCoInitializeEx.Call(0, coinitMultithreaded); r != rpcEChangedMode {
		if err := hr(r, "CoInitializeEx"); err != nil {
			return nil, err
		}
		defer pCoUninitialize.Call()
	}
	hwnd, _, _ := pGetForegroundWindow.Call()
	if hwnd == 0 {
		return nil, errNoFrontWindow
	}
	var uia unsafe.Pointer
	r, _, _ := pCoCreateInstance.Call(uintptr(unsafe.Pointer(&clsidCUIAutomation)), 0, clsctxInprocServer,
		uintptr(unsafe.Pointer(&iidIUIAutomation)), out(&uia))
	if err := hr(r, "UI Automation start"); err != nil {
		return nil, err
	}
	defer release(uia)
	var root, cond, arr unsafe.Pointer
	if err := hr(vcall(uia, vElementFromHandle, hwnd, out(&root)), "ElementFromHandle"); err != nil {
		return nil, err
	}
	defer release(root)
	if err := hr(vcall(uia, vCreateTrueCondition, out(&cond)), "CreateTrueCondition"); err != nil {
		return nil, err
	}
	defer release(cond)
	if err := hr(vcall(root, vFindAll, treeScopeDescendants, uintptr(cond), out(&arr)), "FindAll"); err != nil {
		return nil, err
	}
	defer release(arr)
	var n int32
	if err := hr(vcall(arr, vArrLength, uintptr(unsafe.Pointer(&n))), "array length"); err != nil {
		return nil, err
	}
	var lines []string
	seen := map[string]bool{}
	for i := int32(0); i < n && i < maxElements; i++ {
		var e unsafe.Pointer
		if hr(vcall(arr, vArrGet, uintptr(i), out(&e)), "element") != nil || e == nil {
			continue
		}
		var name *uint16
		if hr(vcall(e, vGetCurrentName, uintptr(unsafe.Pointer(&name))), "name") == nil {
			if s := strings.TrimSpace(bstr(name)); s != "" && !seen[s] {
				seen[s] = true
				lines = append(lines, s)
			}
		}
		lines = append(lines, documentText(e)...)
		release(e)
	}
	return lines, nil
}

// documentText returns the last lines of an element's text area, if it has one.
func documentText(e unsafe.Pointer) []string {
	var tp, rng unsafe.Pointer
	var text *uint16
	if hr(vcall(e, vGetCurrentPatternAs, uiaTextPatternID, uintptr(unsafe.Pointer(&iidIUIATextPattern)), out(&tp)), "text pattern") != nil || tp == nil {
		return nil
	}
	defer release(tp)
	if hr(vcall(tp, vDocumentRange, out(&rng)), "document range") != nil || rng == nil {
		return nil
	}
	defer release(rng)
	if hr(vcall(rng, vGetText, maxTextChars, uintptr(unsafe.Pointer(&text))), "get text") != nil {
		return nil
	}
	all := strings.Split(strings.ReplaceAll(bstr(text), "\r\n", "\n"), "\n")
	if len(all) > MaxTextLines {
		all = all[len(all)-MaxTextLines:]
	}
	return all
}
