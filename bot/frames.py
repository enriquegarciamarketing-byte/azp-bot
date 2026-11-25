"""Saca fotogramas nítidos y distintos de un vídeo (una foto por estancia, sin movidas ni repetidas)."""
import json
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image


def _duration(video):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(video)],
                       capture_output=True, text=True, timeout=60)
    try:
        return float(json.loads(r.stdout)["format"]["duration"])
    except Exception:  # noqa: BLE001
        return 0.0


def _sharpness(gray):
    # varianza del laplaciano: alto = nítido, bajo = movido
    lap = (-4 * gray[1:-1, 1:-1] + gray[:-2, 1:-1] + gray[2:, 1:-1] + gray[1:-1, :-2] + gray[1:-1, 2:])
    return float(lap.var())


def extract(video, out_dir, max_frames=8):
    video, out_dir = Path(video), Path(out_dir)
    dur = _duration(video)
    if dur < 2:
        return []
    cand_dir = out_dir / (video.stem + "_cand")
    cand_dir.mkdir(parents=True, exist_ok=True)
    step = max(0.5, dur / 120)  # como mucho ~120 candidatos
    # candidatos ya a buena resolución: luego se copia el elegido tal cual (sin volver a buscar el instante)
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-vf",
                    f"fps=1/{step},scale='min(1600,iw)':-2", "-q:v", "2", str(cand_dir / "c_%04d.jpg")],
                   timeout=900, check=False)
    cands = []
    for i, f in enumerate(sorted(cand_dir.glob("c_*.jpg"))):
        im = Image.open(f)
        im.thumbnail((480, 480))
        g = np.asarray(im.convert("L"), dtype=np.float32)
        if g.mean() < 25 or g.mean() > 240:  # fotogramas negros o quemados
            continue
        small = np.asarray(im.convert("RGB").resize((32, 18)), dtype=np.float32)
        cands.append({"t": i * step, "sharp": _sharpness(g), "small": small, "file": f})
    if not cands:
        return []
    # la nitidez depende de la estancia (una pared lisa da poco detalle): comparar solo con los vecinos
    for i, c in enumerate(cands):
        near = [o["sharp"] for o in cands[max(0, i - 2):i + 3]]  # ~1 s alrededor: el movimiento es local
        c["ok"] = c["sharp"] >= 0.5 * max(near)
    good = [c for c in cands if c["ok"]]
    # repartir por el vídeo: el más nítido de cada tramo, sin repetir escena
    chosen, n = [], max_frames
    edges = np.linspace(0, dur, n + 1)
    for a, b in zip(edges[:-1], edges[1:]):
        seg = [c for c in good if a <= c["t"] < b]
        for c in sorted(seg, key=lambda c: -c["sharp"]):
            if all(np.abs(c["small"] - o["small"]).mean() > 12 for o in chosen):
                chosen.append(c)
                break
    out = []
    for k, c in enumerate(sorted(chosen, key=lambda c: c["t"])):
        dst = out_dir / f"{video.stem}_f{k}.jpg"
        c["file"].replace(dst)
        out.append(str(dst))
    return out
