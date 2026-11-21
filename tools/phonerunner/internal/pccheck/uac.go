package pccheck

import "fmt"

// UACValues are the three values under
// HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System that T-01C reads.
var UACValues = []struct {
	Name string
	Want uint32
}{
	{"EnableLUA", 1},                  // the prompt system is on
	{"ConsentPromptBehaviorAdmin", 2}, // "Always notify": prompt for every elevation
	{"PromptOnSecureDesktop", 1},      // on the dimmed screen agents cannot click
}

// AlwaysNotify is T-01C: Windows prompts for every elevation, on the secure
// screen. read returns one DWORD value. It reads only and changes nothing. The
// desk command that turns the Run button on refuses unless this passes.
func AlwaysNotify(read func(name string) (uint32, error)) Result {
	const test = "T-01C"
	got := ""
	pass := true
	for _, v := range UACValues {
		n, err := read(v.Name)
		if err != nil {
			return fail(test, "cannot read %s: %v", v.Name, err)
		}
		if n != v.Want {
			pass = false
		}
		got += fmt.Sprintf("%s=%d, ", v.Name, n)
	}
	got = got[:len(got)-2]
	if !pass {
		return fail(test, "Always notify is not on [read: %s; need EnableLUA=1, ConsentPromptBehaviorAdmin=2, PromptOnSecureDesktop=1]", got)
	}
	return Result{Test: test, Pass: true, Detail: "Always notify is on [read: " + got + "]"}
}
