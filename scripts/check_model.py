"""Live model acceptance checks, saving responses without credentials."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageDraw, ImageFont
from src.vision import ROOT, load_profile, review

sys.stdout.reconfigure(encoding="utf-8")
folder = ROOT / "output" / "model_acceptance"
folder.mkdir(parents=True, exist_ok=True)
config = json.loads((ROOT / "config.example.json").read_text(encoding="utf-8"))
profile = load_profile(config)
logo = ROOT / config["logo_reference"]
font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 56)
paths = []
for index, text in enumerate(["0元免费看", "免费看", "一分钱不花", "今天去公园散步"]):
    path = folder / f"text_{index}.png"
    image = Image.new("RGB", (720, 1280), "white")
    ImageDraw.Draw(image).text((40, 600), text, font=font, fill="black")
    image.save(path)
    paths.append(path)
cases = [("phrases", paths[:3], "blocked"), ("clean_reference_is_not_hit", [paths[3]] * 3, "sample_clear"),
         ("logo", [logo, paths[3], paths[3]], "blocked")]
for name, images, expected in cases:
    result = review([{"path": str(p), "seconds": i} for i, p in enumerate(images)], profile, logo)
    (folder / f"{name}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(name, result["status"], "expected", expected, flush=True)
    if result["status"] != expected:
        raise SystemExit(1)
