"""Generate artwork with a local ComfyUI (Z-Image Turbo; MOSS-Image for the chapter card) over its HTTP API.

ComfyUI must be running (run_nvidia_gpu.bat, default http://127.0.0.1:8188; other address: COMFY_HOST).
Usage: python comfy_gen.py OUTDIR "prompt" [seeds=1,2,3] [WxH=1216x832]
"""
import json, os, sys, time, urllib.request, urllib.parse

HOST = os.environ.get("COMFY_HOST", "http://127.0.0.1:8188")
MODEL = "ZImageTurbo\\zImageTurbo_turbo.safetensors"
TEXT_ENCODER = "qwen_3_4b.safetensors"
VAE = "zImage_vae.safetensors"


def workflow(prompt, seed, w, h, steps=9):
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": MODEL, "weight_dtype": "fp8_e4m3fn"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": TEXT_ENCODER, "type": "lumina2"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "4": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1", 0], "shift": 3.0}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": prompt}},
        "6": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["5", 0]}},
        "7": {"class_type": "EmptySD3LatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
        "8": {"class_type": "KSampler", "inputs": {
            "model": ["4", 0], "positive": ["5", 0], "negative": ["6", 0], "latent_image": ["7", 0],
            "seed": seed, "steps": steps, "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple",
            "denoise": 1.0}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "SaveImage", "inputs": {"images": ["9", 0], "filename_prefix": "gsmerge_title"}},
    }


def inpaint_workflow(prompt, seed, image_name, steps=9, denoise=1.0):
    """Repaint the transparent parts of an uploaded RGBA image (LoadImage: mask = 1 - alpha, soft edges via
    Differential Diffusion); opaque parts are kept."""
    wf = workflow(prompt, seed, 64, 64, steps)
    wf["4b"] = {"class_type": "DifferentialDiffusion", "inputs": {"model": ["4", 0]}}
    wf["11"] = {"class_type": "LoadImage", "inputs": {"image": image_name}}
    wf["12"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["11", 0], "vae": ["3", 0]}}
    wf["13"] = {"class_type": "SetLatentNoiseMask", "inputs": {"samples": ["12", 0], "mask": ["11", 1]}}
    del wf["7"]
    wf["8"]["inputs"].update({"model": ["4b", 0], "latent_image": ["13", 0], "denoise": denoise})
    return wf


def moss_workflow(prompt, negative, seed, w, h, steps=25):
    """MOSS-Image SFT text-to-image (ComfyUI 0.42+, models from Comfy-Org/MOSS-Image), the template's settings."""
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "moss_image_sft_int8_convrot.safetensors",
                                                     "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3.5_9b_int8_convrot.safetensors",
                                                     "type": "moss_image", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "flux2-vae_small.safetensors"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": prompt}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": negative}},
        "6": {"class_type": "EmptyFlux2LatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
        "7": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0], "positive": ["4", 0], "negative": ["5", 0], "latent_image": ["6", 0],
            "seed": seed, "steps": steps, "cfg": 2.5, "sampler_name": "er_sde", "scheduler": "simple",
            "denoise": 1.0}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["7", 0], "vae": ["3", 0]}},
        "10": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": "gsmerge_card"}},
    }


def upload(path):
    """Upload a local image to ComfyUI's input folder; returns the name to use in LoadImage."""
    boundary = "----gsmerge" + str(int(time.time() * 1000))
    name = os.path.basename(path)
    crlf = "\r\n"
    head = crlf.join([f"--{boundary}", f'Content-Disposition: form-data; name="image"; filename="{name}"',
                      "Content-Type: image/png", "", ""])
    tail = crlf.join(["", f"--{boundary}", 'Content-Disposition: form-data; name="overwrite"', "", "true",
                      f"--{boundary}--", ""])
    body = head.encode() + open(path, "rb").read() + tail.encode()
    req = urllib.request.Request(HOST + "/upload/image", body,
                                 {"Content-Type": f"multipart/form-data; boundary={boundary}"})
    return json.loads(urllib.request.urlopen(req, timeout=60).read())["name"]


def _get(path):
    return json.loads(urllib.request.urlopen(HOST + path, timeout=30).read())


def run(prompt, seed, w, h, out_path, wf=None):
    body = json.dumps({"prompt": wf or workflow(prompt, seed, w, h)}).encode()
    req = urllib.request.Request(HOST + "/prompt", body, {"Content-Type": "application/json"})
    pid = json.loads(urllib.request.urlopen(req, timeout=30).read())["prompt_id"]
    while True:
        hist = _get("/history/" + pid)
        if pid in hist:
            break
        time.sleep(2)
    status = hist[pid].get("status", {})
    if status.get("status_str") == "error":
        raise RuntimeError(json.dumps(status)[:2000])
    img = hist[pid]["outputs"]["10"]["images"][0]
    q = urllib.parse.urlencode({"filename": img["filename"], "subfolder": img["subfolder"], "type": img["type"]})
    open(out_path, "wb").write(urllib.request.urlopen(HOST + "/view?" + q, timeout=60).read())
    return out_path


if __name__ == "__main__":
    out, prompt = sys.argv[1], sys.argv[2]
    seeds = [int(s) for s in (sys.argv[3] if len(sys.argv) > 3 else "1,2,3").split(",")]
    w, h = map(int, (sys.argv[4] if len(sys.argv) > 4 else "1216x832").split("x"))
    os.makedirs(out, exist_ok=True)
    for s in seeds:
        t = time.time()
        p = run(prompt, s, w, h, os.path.join(out, f"seed{s}.png"))
        print(f"{p}  ({time.time() - t:.0f}s)", flush=True)
