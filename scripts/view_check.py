"""Tell whether a stock photo shows the front of the car, using a small CLIP model (runs on CPU).

Used by update.py so cards show the front of the vehicle, never an interior, engine or rear shot.
If torch or open_clip is not installed the check is skipped and update.py falls back to text rules.
"""
import io, time, urllib.error, urllib.request

_model = None
LABELS = {
    "front": "a photo of the front of a car, showing the headlights and grille",
    "side": "a side view photo of a car",
    "rear": "a photo of the back of a car, showing the taillights and trunk",
    "interior": "a photo of the inside of a car, showing the dashboard, seats or steering wheel",
    "engine": "a photo of a car engine under the hood",
    "detail": "a close up photo of a car part, wheel or badge",
}

def _load():
    global _model
    if _model is None:
        try:
            import torch, open_clip
            model, _, pre = open_clip.create_model_and_transforms("ViT-B-32", pretrained="laion2b_s34b_b79k")
            tok = open_clip.get_tokenizer("ViT-B-32")
            model.eval()
            with torch.no_grad():
                t = model.encode_text(tok(list(LABELS.values())))
                t /= t.norm(dim=-1, keepdim=True)
            _model = (torch, model, pre, t)
        except Exception as e:
            print("view check unavailable:", e)
            _model = False
    return _model

def available():
    return bool(_load())

def view_of(url, ua):
    """Returns (top label, {label: probability}) or None when the image can't be checked."""
    m = _load()
    if not m:
        return None
    torch, model, pre, text = m
    from PIL import Image
    for i in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": ua})
            with urllib.request.urlopen(req, timeout=30) as r:
                img = Image.open(io.BytesIO(r.read())).convert("RGB")
            break
        except urllib.error.HTTPError as e:
            if e.code != 429:
                return None
            time.sleep(5 * (i + 1))
        except Exception:
            return None
    else:
        return None
    with torch.no_grad():
        f = model.encode_image(pre(img).unsqueeze(0))
        f /= f.norm(dim=-1, keepdim=True)
        p = (100 * f @ text.T).softmax(dim=-1)[0].tolist()
    probs = dict(zip(LABELS, (round(x, 3) for x in p)))
    return max(probs, key=probs.get), probs
