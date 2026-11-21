package pccheck

import (
	"errors"
	"strings"
	"testing"
)

func TestAlwaysNotify(t *testing.T) {
	vals := map[string]uint32{"EnableLUA": 1, "ConsentPromptBehaviorAdmin": 2, "PromptOnSecureDesktop": 1}
	read := func(n string) (uint32, error) { return vals[n], nil }
	if r := AlwaysNotify(read); !r.Pass || r.Line() != "PASS T-01C Always notify is on [read: EnableLUA=1, ConsentPromptBehaviorAdmin=2, PromptOnSecureDesktop=1]" {
		t.Fatal(r.Line())
	}
	vals["ConsentPromptBehaviorAdmin"] = 5 // the Windows default notch
	if r := AlwaysNotify(read); r.Pass || !strings.Contains(r.Detail, "ConsentPromptBehaviorAdmin=5") {
		t.Fatal(r.Line())
	}
	if r := AlwaysNotify(func(string) (uint32, error) { return 0, errors.New("denied") }); r.Pass || !strings.Contains(r.Detail, "cannot read EnableLUA") {
		t.Fatal(r.Line())
	}
}
