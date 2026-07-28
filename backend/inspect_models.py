import torch

def inspect(path):
    print(f"\n{'='*60}\n{path}\n{'='*60}")
    try:
        obj = torch.load(path, map_location="cpu", weights_only=False)
    except Exception as e:
        print(f"Failed to load with weights_only=False: {e}")
        try:
            obj = torch.load(path, map_location="cpu", weights_only=True)
        except Exception as e2:
            print(f"Failed with weights_only=True too: {e2}")
            return

    if isinstance(obj, dict):
        print(f"Top-level type: dict with keys: {list(obj.keys())}")
        # Sometimes checkpoints wrap the real state_dict under a key
        state_dict = obj.get("state_dict", obj.get("model_state_dict", obj))
        if isinstance(state_dict, dict):
            print(f"\nNumber of tensor entries: {len(state_dict)}")
            print("First 15 keys + shapes:")
            for i, (k, v) in enumerate(state_dict.items()):
                if i >= 15:
                    break
                shape = tuple(v.shape) if hasattr(v, "shape") else type(v)
                print(f"  {k}: {shape}")
            print("\nLast 5 keys + shapes:")
            items = list(state_dict.items())
            for k, v in items[-5:]:
                shape = tuple(v.shape) if hasattr(v, "shape") else type(v)
                print(f"  {k}: {shape}")
        # Print any other useful metadata keys
        for k in obj.keys():
            if k not in ("state_dict", "model_state_dict"):
                val = obj[k]
                if not hasattr(val, "shape") or (hasattr(val, "numel") and val.numel() < 20):
                    print(f"Metadata '{k}': {val}")
    else:
        print(f"Top-level type: {type(obj)} (likely a full pickled model, not just weights)")
        print(obj)

inspect("trained_models/deepfake_mobilenetv3.pth")
inspect("trained_models/voice_spoof_cnn.pth")
inspect("trained_models/behavioral_isolation_fore.pth")  # fix extension if different