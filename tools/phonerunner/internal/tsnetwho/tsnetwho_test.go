package tsnetwho

import (
	"context"
	"errors"
	"testing"

	"tailscale.com/client/tailscale/apitype"
	"tailscale.com/tailcfg"
)

func TestAdapter(t *testing.T) {
	ctx := context.Background()
	a := Adapter{Fn: func(context.Context, string) (*apitype.WhoIsResponse, error) {
		return &apitype.WhoIsResponse{Node: &tailcfg.Node{StableID: "nX", ComputedName: "pixel"}, UserProfile: &tailcfg.UserProfile{LoginName: "jake@x"}}, nil
	}}
	id, err := a.WhoIs(ctx, "1.2.3.4:5")
	if err != nil || id.NodeID != "nX" || id.Login != "jake@x" || id.NodeName != "pixel" || id.Tagged {
		t.Fatalf("%+v %v", id, err)
	}
	a.Fn = func(context.Context, string) (*apitype.WhoIsResponse, error) {
		return &apitype.WhoIsResponse{Node: &tailcfg.Node{StableID: "nT", Tags: []string{"tag:server"}}}, nil
	}
	if id, _ := a.WhoIs(ctx, ""); !id.Tagged || id.Login != "" {
		t.Fatalf("tagged %+v", id)
	}
	a.Fn = func(context.Context, string) (*apitype.WhoIsResponse, error) { return &apitype.WhoIsResponse{}, nil }
	if _, err := a.WhoIs(ctx, ""); err == nil {
		t.Fatal("nil node accepted")
	}
	a.Fn = func(context.Context, string) (*apitype.WhoIsResponse, error) { return nil, errors.New("down") }
	if _, err := a.WhoIs(ctx, ""); err == nil {
		t.Fatal("error swallowed")
	}
}
