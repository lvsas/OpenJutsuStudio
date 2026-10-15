#!/usr/bin/env python3
"""Télécharge tous les modèles requis dans une installation ComfyUI.

Idempotent : ignore les fichiers déjà présents.
Usage: python3 download_models.py --comfyui /path/to/ComfyUI [--dry-run]
"""
import argparse, os, sys, urllib.request

MODELS = [
    # URLs are public upstream model files; weights are not redistributed here.
    ("https://huggingface.co/comfyicu/LTX-2.5/resolve/main/diffusion_models/"
     "ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors",
     "diffusion_models", "ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors"),
    ("https://huggingface.co/comfyicu/LTX-2.5/resolve/main/text_encoders/"
     "gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors",
     "text_encoders", "gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors"),
    ("https://huggingface.co/comfyicu/LTX-2.5/resolve/main/vae/"
     "ltx-2.5-video-vae-conv-bf16.safetensors",
     "vae", "ltx-2.5-video-vae-conv-bf16.safetensors"),
    ("https://huggingface.co/comfyicu/LTX-2.5/resolve/main/vae/"
     "ltx-2.5-audio-vae-bf16.safetensors",
     "vae", "ltx-2.5-audio-vae-bf16.safetensors"),
    ("https://huggingface.co/WepeNerd/LTX-Ripple/resolve/main/"
     "LTX25_Ripple_v11.safetensors",
     "loras", "LTX25_Ripple_v11.safetensors"),
]


def human(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{u}"
        n /= 1024
    return f"{n:.1f}TB"


def fetch(url, dest, dry):
    if os.path.exists(dest) and os.path.getsize(dest) > 1024:
        print(f"  skip   {os.path.basename(dest)} (deja present)")
        return True
    if dry:
        print(f"  WOULD  {url}")
        return True
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"
    print(f"  get    {os.path.basename(dest)}")
    try:
        with urllib.request.urlopen(url, timeout=60) as r, open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if total:
                    pct = done * 100 // total
                    print(f"\r         {pct:3d}%  {human(done)}/{human(total)}", end="")
        print()
        os.replace(tmp, dest)
        return True
    except Exception as e:
        print(f"\n  FAIL   {e}")
        if os.path.exists(tmp):
            os.remove(tmp)
        return False


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--comfyui", required=True, help="chemin racine de ComfyUI")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()

    root = os.path.join(a.comfyui, "models")
    if not os.path.isdir(os.path.join(a.comfyui, "models")) and not a.dry_run:
        print(f"ERREUR: {root} introuvable. --comfyui doit pointer vers la racine ComfyUI.",
              file=sys.stderr)
        sys.exit(1)

    ok = fail = 0
    for url, folder, name in MODELS:
        dest = os.path.join(root, folder, name)
        if fetch(url, dest, a.dry_run):
            ok += 1
        else:
            fail += 1

    print(f"\n{ok} ok, {fail} echecs.")
    if fail:
        print("Verifiez votre connexion, ou telechargez les fichiers manuellement "
              "(voir README > Models).", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
