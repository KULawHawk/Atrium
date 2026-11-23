package tslog

import (
	"sync"
	"testing"
)

func TestOnce(t *testing.T) {
	var got []string
	log := Once(func(l string) { got = append(got, l) })
	for i := 0; i < 50; i++ {
		log("NeedsLogin: go to: %s\n", "https://login.tailscale.com/a/abc")
	}
	log("joined")
	log("NeedsLogin: go to: %s", "https://login.tailscale.com/a/abc")
	log("go to: https://login.tailscale.com/a/new")
	want := []string{"NeedsLogin: go to: https://login.tailscale.com/a/abc", Waiting, "joined", "go to: https://login.tailscale.com/a/new"}
	if len(got) != len(want) {
		t.Fatalf("got %q", got)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("line %d: got %q want %q", i, got[i], want[i])
		}
	}
}

func TestOnceConcurrent(t *testing.T) {
	var mu sync.Mutex
	n := 0
	log := Once(func(string) { mu.Lock(); n++; mu.Unlock() })
	var wg sync.WaitGroup
	for i := 0; i < 20; i++ {
		wg.Add(1)
		go func() { defer wg.Done(); log("same line") }()
	}
	wg.Wait()
	if n != 2 { // the line once, then the waiting line once
		t.Fatalf("printed %d lines", n)
	}
}
