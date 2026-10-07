import platform
import subprocess
import threading
import tkinter as tk
from tkinter import ttk
import cv2
from PIL import Image, ImageTk

IS_WINDOWS = platform.system() == "Windows"

CAM_INDEX = 0
DEVICE = "/dev/video0" if not IS_WINDOWS else f"CAM_{CAM_INDEX}"

# --- Limites e passos ---
# No Linux: Arco-segundos (-216000 a 216000 => -60° a 60°)
# No Windows: Graus (-60° a 60°)
if IS_WINDOWS:
    PAN_MIN, PAN_MAX   = -60, 60
    TILT_MIN, TILT_MAX = -45, 45
    PAN_STEP  = 3
    TILT_STEP = 3
    ZOOM_MIN, ZOOM_MAX = 1, 10
    ZOOM_STEP = 1
else:
    PAN_MIN, PAN_MAX   = -216000, 216000
    TILT_MIN, TILT_MAX = -162000, 162000
    PAN_STEP  = 10000
    TILT_STEP = 10000
    ZOOM_MIN, ZOOM_MAX = 40, 240
    ZOOM_STEP = 10

pan_value   = 0
tilt_value  = 0
zoom_value  = ZOOM_MIN
brightness_value = 50
plf_value   = 2
PLF_OPTIONS = {0: "Desligado", 1: "50 Hz", 2: "60 Hz"}

cap = None
cap_lock = threading.Lock()
running = True

# ── Controle de Câmera ──────────────────────────────────────────────

def set_ctrl(control, value):
    """Envia o comando respeitando o driver de cada sistema operacional."""
    if not IS_WINDOWS:
        # Modo Linux via v4l2-ctl
        try:
            subprocess.run(
                ["v4l2-ctl", "-d", DEVICE, f"--set-ctrl={control}={value}"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            print(f"Erro Linux: {e}")
    else:
        # Modo Windows: controle direto via DirectShow
        with cap_lock:
            if cap is not None and cap.isOpened():
                sucesso = False
                if control == "pan_absolute":
                    sucesso = cap.set(cv2.CAP_PROP_PAN, float(value))
                elif control == "tilt_absolute":
                    sucesso = cap.set(cv2.CAP_PROP_TILT, float(value))
                elif control == "zoom_absolute":
                    sucesso = cap.set(cv2.CAP_PROP_ZOOM, float(value))
                elif control == "brightness":
                    sucesso = cap.set(cv2.CAP_PROP_BRIGHTNESS, float(value))
                
                if not sucesso:
                    print(f"[Windows] Não foi possível aplicar {control}={value}. Verifique suporte do driver UVC.")


def move_left():
    global pan_value
    pan_value = max(PAN_MIN, pan_value - PAN_STEP)
    set_ctrl("pan_absolute", pan_value)
    update_labels()

def move_right():
    global pan_value
    pan_value = min(PAN_MAX, pan_value + PAN_STEP)
    set_ctrl("pan_absolute", pan_value)
    update_labels()

def move_up():
    global tilt_value
    tilt_value = min(TILT_MAX, tilt_value + TILT_STEP)
    set_ctrl("tilt_absolute", tilt_value)
    update_labels()

def move_down():
    global tilt_value
    tilt_value = max(TILT_MIN, tilt_value - TILT_STEP)
    set_ctrl("tilt_absolute", tilt_value)
    update_labels()

def zoom_in():
    global zoom_value
    zoom_value = min(ZOOM_MAX, zoom_value + ZOOM_STEP)
    set_ctrl("zoom_absolute", zoom_value)
    update_labels()

def zoom_out():
    global zoom_value
    zoom_value = max(ZOOM_MIN, zoom_value - ZOOM_STEP)
    set_ctrl("zoom_absolute", zoom_value)
    update_labels()

def go_home():
    global pan_value, tilt_value, zoom_value
    pan_value   = 0
    tilt_value  = 0
    zoom_value  = ZOOM_MIN
    set_ctrl("pan_absolute", pan_value)
    set_ctrl("tilt_absolute", tilt_value)
    set_ctrl("zoom_absolute", zoom_value)
    update_labels()

def change_brightness(val):
    global brightness_value
    try:
        brightness_value = int(float(val))
    except ValueError:
        return
    set_ctrl("brightness", brightness_value)

def change_plf(event=None):
    global plf_value
    name = plf_combo.get()
    for k, v in PLF_OPTIONS.items():
        if v == name:
            plf_value = k
            set_ctrl("power_line_frequency", plf_value)
            break

def save_preset(slot):
    presets[slot] = (pan_value, tilt_value, zoom_value)
    preset_buttons[slot].config(bg="#4CAF50", text=f"Preset {slot+1} ✓")

def load_preset(slot):
    global pan_value, tilt_value, zoom_value
    if presets[slot] is None:
        return
    pan_value, tilt_value, zoom_value = presets[slot]
    set_ctrl("pan_absolute", pan_value)
    set_ctrl("tilt_absolute", tilt_value)
    set_ctrl("zoom_absolute", zoom_value)
    update_labels()

def update_labels():
    unidade = "°" if IS_WINDOWS else ""
    lbl_pan.config(text=f"Pan:  {pan_value}{unidade}")
    lbl_tilt.config(text=f"Tilt: {tilt_value}{unidade}")
    lbl_zoom.config(text=f"Zoom: {zoom_value}")

# ── Captura de vídeo ────────────────────────────────────────────────

def video_loop():
    global cap, running

    # No Windows, cv2.CAP_DSHOW é OBRIGATÓRIO para expor o IAMCameraControl
    if IS_WINDOWS:
        cap = cv2.VideoCapture(CAM_INDEX, cv2.CAP_DSHOW)
    else:
        cap = cv2.VideoCapture(CAM_INDEX)

    if not cap.isOpened():
        status_label.config(text="Não foi possível abrir a câmera", fg="#f38ba8")
        return

    status_label.config(text="Câmera OK", fg="#a6e3a1")

    # Aplica posições iniciais
    go_home()

    while running:
        with cap_lock:
            ret, frame = cap.read()

        if not ret or frame is None:
            continue

        frame = cv2.resize(frame, (480, 270))
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        img = Image.fromarray(frame)
        imgtk = ImageTk.PhotoImage(image=img)

        video_label.imgtk = imgtk
        video_label.configure(image=imgtk)

        root.after(30)

    with cap_lock:
        if cap is not None:
            cap.release()

def on_close():
    global running
    running = False
    root.destroy()

# ── UI Tkinter ──────────────────────────────────────────────────────

root = tk.Tk()
root.title("HTI-UC390 PTZ Control")
root.configure(bg="#1e1e2e")
root.resizable(False, False)
root.protocol("WM_DELETE_WINDOW", on_close)

BG      = "#1e1e2e"
BTN_BG  = "#313244"
BTN_FG  = "#cdd6f4"
ACC     = "#89b4fa"
FONT    = ("Segoe UI", 12, "bold")
FONT_SM = ("Segoe UI", 10)

def make_btn(parent, text, cmd, color=BTN_BG, fg=BTN_FG, size=FONT, w=5, h=2):
    return tk.Button(
        parent, text=text, command=cmd,
        bg=color, fg=fg, font=size,
        width=w, height=h,
        relief="flat", cursor="hand2",
        activebackground=ACC, activeforeground="#1e1e2e"
    )

# Título
tk.Label(root, text="🎥  HTI-UC390 — PTZ + Preview",
         bg=BG, fg=ACC, font=("Segoe UI", 14, "bold")).grid(
         row=0, column=0, columnspan=2, pady=(10, 5))

# Preview
frame_video = tk.Frame(root, bg=BG)
frame_video.grid(row=1, column=0, padx=10, pady=5)

video_label = tk.Label(frame_video, bg="#000000")
video_label.pack(padx=5, pady=5)

status_label = tk.Label(frame_video, text="Iniciando câmera...",
                        bg=BG, fg="#f9e2af", font=FONT_SM)
status_label.pack(pady=(0, 5))

# Controles
frame_controls = tk.Frame(root, bg=BG)
frame_controls.grid(row=1, column=1, padx=10, pady=5, sticky="n")

# Direcionais
frame_dir = tk.Frame(frame_controls, bg=BG)
frame_dir.grid(row=0, column=0, pady=(0, 10))

make_btn(frame_dir, "▲", move_up).grid(   row=0, column=1, padx=4, pady=4)
make_btn(frame_dir, "◀", move_left).grid( row=1, column=0, padx=4, pady=4)
make_btn(frame_dir, "⌂", go_home, color="#45475a").grid(row=1, column=1, padx=4, pady=4)
make_btn(frame_dir, "▶", move_right).grid(row=1, column=2, padx=4, pady=4)
make_btn(frame_dir, "▼", move_down).grid( row=2, column=1, padx=4, pady=4)

# Zoom
frame_zoom = tk.Frame(frame_controls, bg=BG)
frame_zoom.grid(row=1, column=0, pady=(0, 10))

tk.Label(frame_zoom, text="Zoom", bg=BG, fg=BTN_FG, font=FONT_SM).pack()
make_btn(frame_zoom, "＋", zoom_in,  color="#313244", w=6, h=1).pack(pady=2)
make_btn(frame_zoom, "－", zoom_out, color="#313244", w=6, h=1).pack(pady=2)

# Status PTZ
frame_status = tk.Frame(frame_controls, bg="#313244", padx=8, pady=6)
frame_status.grid(row=2, column=0, pady=5, sticky="ew")

tk.Label(frame_status, text="Posição PTZ", bg="#313244", fg=ACC, font=FONT_SM).pack()
lbl_pan  = tk.Label(frame_status, text="Pan:  0",  bg="#313244", fg=BTN_FG, font=FONT_SM)
lbl_tilt = tk.Label(frame_status, text="Tilt: 0",  bg="#313244", fg=BTN_FG, font=FONT_SM)
lbl_zoom = tk.Label(frame_status, text="Zoom: 1",  bg="#313244", fg=BTN_FG, font=FONT_SM)
lbl_pan.pack()
lbl_tilt.pack()
lbl_zoom.pack()

# Brilho
frame_image = tk.Frame(frame_controls, bg=BG)
frame_image.grid(row=3, column=0, pady=(5, 10), sticky="ew")

tk.Label(frame_image, text="Brilho", bg=BG, fg=BTN_FG, font=FONT_SM).grid(row=0, column=0, sticky="w")
brightness_scale = tk.Scale(
    frame_image, from_=0, to=100,
    orient="horizontal", bg=BG, fg=BTN_FG,
    troughcolor="#45475a", highlightthickness=0,
    command=change_brightness, length=160
)
brightness_scale.set(brightness_value)
brightness_scale.grid(row=1, column=0, pady=(0, 5))

# Frequência
tk.Label(frame_image, text="Frequência (luz)", bg=BG, fg=BTN_FG, font=FONT_SM).grid(row=2, column=0, sticky="w", pady=(5, 0))
plf_combo = ttk.Combobox(frame_image, values=list(PLF_OPTIONS.values()), state="readonly", width=14)
plf_combo.set(PLF_OPTIONS[plf_value])
plf_combo.grid(row=3, column=0, pady=(0, 5))
plf_combo.bind("<<ComboboxSelected>>", change_plf)

style = ttk.Style()
style.theme_use("clam")
style.configure("TCombobox", fieldbackground=BG, background="#45475a", foreground=BTN_FG)

# Presets
tk.Label(frame_controls, text="Presets de posição",
         bg=BG, fg=ACC, font=FONT_SM).grid(row=4, column=0, pady=(5, 2))

frame_presets = tk.Frame(frame_controls, bg=BG)
frame_presets.grid(row=5, column=0, pady=(0, 5))

NUM_PRESETS = 4
presets        = [None] * NUM_PRESETS
preset_buttons = []

for i in range(NUM_PRESETS):
    col_frame = tk.Frame(frame_presets, bg=BG)
    col_frame.pack(side="left", padx=4)

    btn = make_btn(col_frame, f"P{i+1}", lambda s=i: load_preset(s), w=4, h=1)
    btn.pack()
    preset_buttons.append(btn)

    make_btn(col_frame, "Save", lambda s=i: save_preset(s),
             color="#45475a", fg="#a6e3a1", size=FONT_SM, w=4, h=1).pack(pady=2)

# Rodapé
tk.Label(root, text=f"Modo: {'Windows (DirectShow - Graus)' if IS_WINDOWS else 'Linux (V4L2 - Arco-segundos)'}",
         bg=BG, fg="#585b70", font=("Segoe UI", 9)).grid(
         row=2, column=0, columnspan=2, pady=(0, 8))

update_labels()

t = threading.Thread(target=video_loop, daemon=True)
t.start()

root.mainloop()
