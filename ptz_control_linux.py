import os
import subprocess
import threading
import time
import tkinter as tk
import cv2
import numpy as np
from PIL import Image, ImageTk

DEVICE = "/dev/video0"

# Parâmetros de enquadramento
pan_pct   = 0.0       # -100% a +100%
tilt_pct  = 0.0       # -100% a +100%
zoom_val  = 1.3       # Zoom inicial
running   = True

# Auto-Framing State
auto_framing_enabled = False
target_pan  = 0.0
target_tilt = 0.0
target_zoom = 1.3

cap = None
cap_lock = threading.Lock()
latest_frame = None

# ── Carregamento Seguro do Classificador Facial ─────────────────────
face_cascade = None
has_detector = False

try:
    if hasattr(cv2, "CascadeClassifier") and hasattr(cv2, "data"):
        xml_path = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
        if os.path.exists(xml_path):
            face_cascade = cv2.CascadeClassifier(xml_path)
            has_detector = not face_cascade.empty()
except Exception as e:
    has_detector = False

# ── Matemática ePTZ ──────────────────────────────────────────────────

def apply_eptz(frame, pan, tilt, zoom):
    h, w = frame.shape[:2]
    zoom = max(1.0, zoom)

    crop_w = int(w / zoom)
    crop_h = int(h / zoom)

    max_dx = (w - crop_w) // 2
    max_dy = (h - crop_h) // 2

    dx = int((pan / 100.0) * max_dx)
    dy = int((tilt / 100.0) * max_dy)

    cx = (w // 2) + dx
    cy = (h // 2) - dy

    x1 = max(0, min(w - crop_w, cx - crop_w // 2))
    y1 = max(0, min(h - crop_h, cy - crop_h // 2))

    return frame[y1:y1 + crop_h, x1:x1 + crop_w]

# ── Algoritmo de Auto-Framing ────────────────────────────────────────

def process_autoframing(frame_4k):
    global target_pan, target_tilt, target_zoom
    if not has_detector or face_cascade is None:
        return

    h, w = frame_4k.shape[:2]
    scale = 0.25
    small = cv2.resize(frame_4k, (0, 0), fx=scale, fy=scale)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

    faces = face_cascade.detectMultiScale(
        gray, scaleFactor=1.2, minNeighbors=4, minSize=(30, 30)
    )

    if len(faces) > 0:
        min_x = min(f[0] for f in faces)
        min_y = min(f[1] for f in faces)
        max_x = max(f[0] + f[2] for f in faces)
        max_y = max(f[1] + f[3] for f in faces)

        min_x, max_x = int(min_x / scale), int(max_x / scale)
        min_y, max_y = int(min_y / scale), int(max_y / scale)

        center_x = (min_x + max_x) // 2
        center_y = (min_y + max_y) // 2
        box_h = max_y - min_y

        target_pan = ((center_x - (w / 2)) / (w / 2)) * 100.0
        target_tilt = -((center_y - (h / 2)) / (h / 2)) * 100.0

        face_ratio = box_h / h
        if face_ratio > 0:
            desired_zoom = 0.35 / face_ratio
            target_zoom = max(1.2, min(3.0, desired_zoom))

def update_smooth_tracking():
    global pan_pct, tilt_pct, zoom_val
    if auto_framing_enabled and has_detector:
        smoothing = 0.08
        pan_pct  += (target_pan - pan_pct) * smoothing
        tilt_pct += (target_tilt - tilt_pct) * smoothing
        zoom_val += (target_zoom - zoom_val) * smoothing
        update_labels()

# ── Thread de Captura GStreamer 4K ──────────────────────────────────

def capture_worker():
    global cap, running, latest_frame

    gst_pipeline = (
        f"v4l2src device={DEVICE} ! "
        f"video/x-h264,width=3840,height=2160,framerate=30/1 ! "
        f"h264parse ! avdec_h264 ! videoconvert ! "
        f"video/x-raw,format=BGR ! appsink drop=1"
    )

    cap = cv2.VideoCapture(gst_pipeline, cv2.CAP_GSTREAMER)

    if not cap.isOpened():
        cap = cv2.VideoCapture(DEVICE, cv2.CAP_V4L2)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    lbl_sensor.config(text=f"Sensor: {w}x{h} ({'4K H.264' if w > 1920 else '1080p'})")

    frame_count = 0
    while running:
        ret, frame = cap.read()
        if ret and frame is not None:
            with cap_lock:
                latest_frame = frame

            frame_count += 1
            if auto_framing_enabled and frame_count % 3 == 0:
                process_autoframing(frame)
        else:
            time.sleep(0.01)

    if cap:
        cap.release()

# ── Ações e Controles ────────────────────────────────────────────────

def toggle_autoframing():
    global auto_framing_enabled
    if not has_detector:
        lbl_sensor.config(text="Instale opencv-python completo para Auto-Framing", fg="#f38ba8")
        return

    auto_framing_enabled = not auto_framing_enabled

    # Envia sinal de hardware se houver
    val = 1 if auto_framing_enabled else 0
    subprocess.run(["v4l2-ctl", "-d", DEVICE, f"--set-ctrl=auto_framing={val}"], stderr=subprocess.DEVNULL)

    if auto_framing_enabled:
        btn_autoframing.config(text="👤 Auto-Framing: ATIVADO", bg="#a6e3a1", fg="#181825")
    else:
        btn_autoframing.config(text="👤 Auto-Framing: DESATIVADO", bg="#313244", fg="#cdd6f4")

def move(d_pan, d_tilt):
    global pan_pct, tilt_pct, auto_framing_enabled
    if auto_framing_enabled:
        toggle_autoframing()

    pan_pct  = max(-100.0, min(100.0, pan_pct + d_pan))
    tilt_pct = max(-100.0, min(100.0, tilt_pct + d_tilt))
    update_labels()

def zoom(delta):
    global zoom_val, auto_framing_enabled
    if auto_framing_enabled:
        toggle_autoframing()

    zoom_val = max(1.0, min(4.0, round(zoom_val + delta, 2)))
    update_labels()

def reset():
    global pan_pct, tilt_pct, zoom_val, target_pan, target_tilt, target_zoom
    pan_pct, tilt_pct, zoom_val = 0.0, 0.0, 1.3
    target_pan, target_tilt, target_zoom = 0.0, 0.0, 1.3
    update_labels()

def on_click_navigate(event):
    global pan_pct, tilt_pct, auto_framing_enabled
    if auto_framing_enabled:
        toggle_autoframing()

    if zoom_val <= 1.0:
        return
    nx = (event.x / 560.0) - 0.5
    ny = (event.y / 315.0) - 0.5
    pan_pct  = max(-100.0, min(100.0, pan_pct + (nx * 40)))
    tilt_pct = max(-100.0, min(100.0, tilt_pct - (ny * 40)))
    update_labels()

def update_labels():
    lbl_pan.config(text=f"Pan:  {int(pan_pct):+d}%")
    lbl_tilt.config(text=f"Tilt: {int(tilt_pct):+d}%")
    lbl_zoom.config(text=f"Zoom: {zoom_val:.2f}x")

def update_ui():
    if not running:
        return

    update_smooth_tracking()

    frame_to_show = None
    with cap_lock:
        if latest_frame is not None:
            frame_to_show = latest_frame.copy()

    if frame_to_show is not None:
        cropped = apply_eptz(frame_to_show, pan_pct, tilt_pct, zoom_val)
        preview = cv2.resize(cropped, (560, 315), interpolation=cv2.INTER_LINEAR)
        rgb = cv2.cvtColor(preview, cv2.COLOR_BGR2RGB)

        img = ImageTk.PhotoImage(image=Image.fromarray(rgb))
        lbl_video.imgtk = img
        lbl_video.configure(image=img)

    root.after(30, update_ui)

def on_close():
    global running
    running = False
    root.destroy()

# ── Interface Tkinter ────────────────────────────────────────────────

root = tk.Tk()
root.title("Dahua UC390 — 4K ePTZ")
root.configure(bg="#181825")
root.protocol("WM_DELETE_WINDOW", on_close)

# Painel de Vídeo
left = tk.Frame(root, bg="#181825")
left.grid(row=0, column=0, padx=10, pady=10)

lbl_video = tk.Label(left, bg="#000000", width=560, height=315)
lbl_video.pack()
lbl_video.bind("<Button-1>", on_click_navigate)
lbl_video.bind("<B1-Motion>", on_click_navigate)

lbl_sensor = tk.Label(left, text="Iniciando 4K H.264...", bg="#181825", fg="#a6e3a1", font=("Segoe UI", 9))
lbl_sensor.pack(pady=4)

# Painel Lateral
right = tk.Frame(root, bg="#181825")
right.grid(row=0, column=1, padx=(0, 10), pady=10, sticky="n")

# BOTÃO DE AUTO-FRAMING
btn_autoframing = tk.Button(
    right,
    text="👤 Auto-Framing: DESATIVADO" if has_detector else "👤 Auto-Framing (Indisponível)",
    command=toggle_autoframing,
    bg="#313244", fg="#cdd6f4", font=("Segoe UI", 9, "bold"),
    relief="flat", cursor="hand2", padx=6, pady=6
)
btn_autoframing.pack(fill="x", pady=(0, 10))

# D-Pad
pad = tk.Frame(right, bg="#181825")
pad.pack(pady=4)

def make_btn(p, t, cmd, w=5, h=2):
    return tk.Button(p, text=t, command=cmd, bg="#313244", fg="#cdd6f4",
                     font=("Segoe UI", 10, "bold"), width=w, height=h, relief="flat", cursor="hand2")

make_btn(pad, "▲", lambda: move(0, 10)).grid(row=0, column=1, pady=2)
make_btn(pad, "◀", lambda: move(-10, 0)).grid(row=1, column=0, padx=2)
make_btn(pad, "⌂", reset).grid(row=1, column=1, padx=2)
make_btn(pad, "▶", lambda: move(10, 0)).grid(row=1, column=2, padx=2)
make_btn(pad, "▼", lambda: move(0, -10)).grid(row=2, column=1, pady=2)

# Zoom
z_pad = tk.Frame(right, bg="#181825")
z_pad.pack(pady=4)
make_btn(z_pad, "＋ Zoom", lambda: zoom(0.2), w=8, h=1).pack(pady=2)
make_btn(z_pad, "－ Zoom", lambda: zoom(-0.2), w=8, h=1).pack(pady=2)

# Status
status_box = tk.Frame(right, bg="#1e1e2e", padx=10, pady=8)
status_box.pack(fill="x", pady=8)
lbl_pan  = tk.Label(status_box, text="Pan:  0%", bg="#1e1e2e", fg="#cdd6f4")
lbl_tilt = tk.Label(status_box, text="Tilt: 0%", bg="#1e1e2e", fg="#cdd6f4")
lbl_zoom = tk.Label(status_box, text=f"Zoom: {zoom_val:.2f}x", bg="#1e1e2e", fg="#cdd6f4")
lbl_pan.pack()
lbl_tilt.pack()
lbl_zoom.pack()

update_labels()

threading.Thread(target=capture_worker, daemon=True).start()
root.after(100, update_ui)
root.mainloop()
