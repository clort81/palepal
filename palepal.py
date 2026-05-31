#!/usr/bin/env python3
#1.  **Program Name:** Updated to `palepal`.
#2.  **Custom File Dialog:** Replaced the OS native dialog with a custom Tkinter window (`CustomFileDialog`) that allows listing 3x more files by using a smaller font and larger listbox.
#3.  **Persistent State:** Automatically saves/loads preferences (`zoom`, `dot_scale`, `last_file`, `colorspace`) to `~/.config/palepal/palepal_state.ini`.
#4.  **Palette Name:** Added a label in the toolbar showing the current filename.
#5.  **Default HSV:** Starts in HSV mode.
#6.  **2D Screen Scale:** Added `self.screen_scale` variable and logic to zoom the 2D view without changing perspective. Mapped to **Ctrl+MouseWheel**.

# palepal.py

import tkinter as tk
from tkinter import messagebox, simpledialog
import math
import os
import sys
import configparser
import platform

# --- Configuration & State Management ---

APP_NAME = "palepal"
# Cross-platform config directory
if platform.system() == "Windows":
    CONFIG_DIR = os.path.join(os.getenv('APPDATA'), APP_NAME)
else:
    CONFIG_DIR = os.path.join(os.path.expanduser('~'), '.config', APP_NAME)

CONFIG_FILE = os.path.join(CONFIG_DIR, f"{APP_NAME}_state.ini")

def ensure_config_dir():
    if not os.path.exists(CONFIG_DIR):
        try:
            os.makedirs(CONFIG_DIR)
        except OSError as e:
            print(f"Warning: Could not create config dir {CONFIG_DIR}: {e}")

def save_state(state_dict):
    ensure_config_dir()
    config = configparser.ConfigParser()
    config['DEFAULT'] = state_dict
    try:
        with open(CONFIG_FILE, 'w') as f:
            config.write(f)
    except Exception as e:
        print(f"Warning: Could not save state: {e}")

def load_state():
    if not os.path.exists(CONFIG_FILE):
        return {}
    config = configparser.ConfigParser()
    try:
        config.read(CONFIG_FILE)
        # Helper to get float/int with defaults
        def get(key, dtype, default):
            try:
                return dtype(config['DEFAULT'].get(key, default))
            except ValueError:
                return default
            
        return {
            'last_file': config['DEFAULT'].get('last_file', ''),
            'viewer_distance': get('viewer_distance', float, 2.66),
            'point_scale': get('point_scale', float, 1.0),
            'colorspace': config['DEFAULT'].get('colorspace', 'HSV'),
            'screen_scale': get('screen_scale', float, 1.0)
        }
    except Exception as e:
        print(f"Warning: Could not load state: {e}")
        return {}

# --- 3D Geometry & Math Helpers ---

def rotate_all(x, y, z, ax, ay, az):
    """Combined rotation returning a tuple to avoid object allocation."""
    # Rotate X
    cx, sx = math.cos(ax), math.sin(ax)
    y, z = y*cx - z*sx, y*sx + z*cx
    
    # Rotate Y
    cy, sy = math.cos(ay), math.sin(ay)
    new_z = z*cy - x*sy
    new_x = z*sy + x*cy
    x, z = new_x, new_z
    
    # Rotate Z
    cz, sz = math.cos(az), math.sin(az)
    new_x = x*cz - y*sz
    new_y = x*sz + y*cz
    x, y = new_x, new_y
    
    return x, y, z

# --- Color Conversion Logic ---

class ColorConverter:
    
    @staticmethod
    def rgb_to_xyz(r, g, b):
        r, g, b = r/255.0, g/255.0, b/255.0
        
        def correct(c):
            return ((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92
        
        r, g, b = correct(r), correct(g), correct(b)
        x = r * 0.4124564 + g * 0.3575761 + b * 0.1804375
        y = r * 0.2126729 + g * 0.7151522 + b * 0.0721750
        z = r * 0.0193339 + g * 0.1191920 + b * 0.9503041
        return x, y, z

    @staticmethod
    def xyz_to_lab(x, y, z):
        xn, yn, zn = 0.95047, 1.0, 1.08883
        
        def f(t):
            return t ** (1/3) if t > 0.008856 else 7.787 * t + 16/116
        
        lx = f(x / xn)
        ly = f(y / yn)
        lz = f(z / zn)
        
        L = (116 * ly) - 16
        a = 500 * (lx - ly)
        b = 200 * (ly - lz)
        return L, a, b

    @staticmethod
    def rgb_to_oklab(r, g, b):
        r, g, b = r/255.0, g/255.0, b/255.0
        
        def correct(c):
            return ((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92
        
        r, g, b = correct(r), correct(g), correct(b)
        
        l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
        m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
        s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
        
        l_ = l ** (1/3)
        m_ = m ** (1/3)
        s_ = s ** (1/3)
        
        L = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
        a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
        b = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
        
        return L, a, b

    @staticmethod
    def rgb_to_hsv(r, g, b):
        r, g, b = r/255.0, g/255.0, b/255.0
        mx = max(r, g, b)
        mn = min(r, g, b)
        df = mx - mn
        h = 0
        if mx == mn:
            h = 0
        elif mx == r:
            h = (60 * ((g - b) / df) + 360) % 360
        elif mx == g:
            h = (60 * ((b - r) / df) + 120) % 360
        elif mx == b:
            h = (60 * ((r - g) / df) + 240) % 360
        s = 0 if mx == 0 else df / mx
        v = mx
        return h, s, v

    @staticmethod
    def get_coords(mode, r, g, b):
        # Y-axis (Vertical) is mapped to Lightness/Intensity.
        if mode == "RGB":
            return r/255.0, b/255.0, g/255.0
        elif mode == "HSV":
            h, s, v = ColorConverter.rgb_to_hsv(r, g, b)
            rad = math.radians(h)
            sx = 0.5 + (s * math.cos(rad) * 0.5)
            sz = 0.5 + (s * math.sin(rad) * 0.5)
            sy = v
            return sx, sy, sz
        elif mode == "CIELAB":
            x, y, z = ColorConverter.rgb_to_xyz(r, g, b)
            L, a, b_val = ColorConverter.xyz_to_lab(x, y, z)
            nx = (a + 128) / 256.0
            nz = (b_val + 128) / 256.0
            ny = L / 100.0
            return nx, ny, nz
        elif mode == "LCH (Polar)":
            x, y, z = ColorConverter.rgb_to_xyz(r, g, b)
            L, a, b_val = ColorConverter.xyz_to_lab(x, y, z)
            C = math.sqrt(a**2 + b_val**2)
            H = math.degrees(math.atan2(b_val, a))
            if H < 0: H += 360
            rad = math.radians(H)
            radius = (C / 150.0) * 0.5
            sx = 0.5 + (radius * math.cos(rad))
            sz = 0.5 + (radius * math.sin(rad))
            sy = L / 100.0
            return sx, sy, sz
        elif mode == "Oklab":
            L, a, b_val = ColorConverter.rgb_to_oklab(r, g, b)
            nx = (a + 0.4) / 0.8
            nz = (b_val + 0.4) / 0.8
            ny = L
            return nx, ny, nz
        return 0, 0, 0

# --- Custom File Dialog (High Density) ---

class CustomFileDialog(tk.Toplevel):
    def __init__(self, parent, initialdir=None):
        super().__init__(parent)
        self.title("Select GIMP Palette")
        self.geometry("600x500")
        self.result = None
        self.current_path = os.path.abspath(initialdir or os.getcwd())
        
        # --- UI ---
        
        # Top Frame: Path and Up Button
        top_frame = tk.Frame(self)
        top_frame.pack(fill=tk.X, padx=5, pady=5)
        
        self.path_var = tk.StringVar(value=self.current_path)
        entry = tk.Entry(top_frame, textvariable=self.path_var)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,5))
        entry.bind('<Return>', lambda e: self.go_path())
        
        btn_up = tk.Button(top_frame, text="Go / Up", command=self.go_path)
        btn_up.pack(side=tk.RIGHT)

        # Middle Frame: File List (Dense)
        list_frame = tk.Frame(self)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Smaller font to fit 3x more files
        self.file_list = tk.Listbox(list_frame, yscrollcommand=scrollbar.set, 
                                    selectmode=tk.SINGLE, font=('Arial', 9))
        self.file_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.file_list.yview)
        
        self.file_list.bind('<Double-Button-1>', self.on_double_click)

        # Bottom Frame: Buttons
        bottom_frame = tk.Frame(self)
        bottom_frame.pack(fill=tk.X, padx=5, pady=5)
        
        btn_cancel = tk.Button(bottom_frame, text="Cancel", command=self.destroy)
        btn_cancel.pack(side=tk.RIGHT, padx=5)
        
        btn_open = tk.Button(bottom_frame, text="Open", command=self.on_open)
        btn_open.pack(side=tk.RIGHT)

        self.update_list()
        self.transient(parent)
        self.grab_set()
        self.wait_window()

    def update_list(self):
        self.file_list.delete(0, tk.END)
        self.path_var.set(self.current_path)
        
        try:
            files = os.listdir(self.current_path)
            # Sort directories first, then files
            dirs = sorted([f for f in files if os.path.isdir(os.path.join(self.current_path, f))])
            gpl_files = sorted([f for f in files if f.lower().endswith('.gpl')])
            
            self.file_list.insert(tk.END, "..")
            for d in dirs:
                self.file_list.insert(tk.END, f"[{d}]")
            for f in gpl_files:
                self.file_list.insert(tk.END, f)
        except PermissionError:
            messagebox.showerror("Error", "Permission denied")

    def go_path(self):
        # Try to read from entry or handle ".." selection
        selection = self.file_list.curselection()
        if selection:
            idx = selection[0]
            text = self.file_list.get(idx)
            if text == "..":
                self.current_path = os.path.dirname(self.current_path)
            elif text.startswith("[") and text.endswith("]"):
                self.current_path = os.path.join(self.current_path, text[1:-1])
            else:
                # It's a file, we are just refreshing or opening
                if not text.lower().endswith('.gpl'):
                    return
                self.result = os.path.join(self.current_path, text)
                self.destroy()
                return
        else:
            # Read from entry
            p = self.path_var.get()
            if os.path.isdir(p):
                self.current_path = os.path.abspath(p)
        
        self.update_list()

    def on_double_click(self, event):
        self.go_path()

    def on_open(self):
        selection = self.file_list.curselection()
        if not selection:
            return
        idx = selection[0]
        text = self.file_list.get(idx)
        
        if text == "..":
            self.current_path = os.path.dirname(self.current_path)
            self.update_list()
        elif text.startswith("["):
            self.current_path = os.path.join(self.current_path, text[1:-1])
            self.update_list()
        elif text.lower().endswith('.gpl'):
            self.result = os.path.join(self.current_path, text)
            self.destroy()

# --- Main Application ---

class PaletteViewer3D:
    def __init__(self, root):
        self.root = root
        self.root.title("PalePal")
        self.root.geometry("800x600")
        
        # Load State
        state = load_state()
        self.current_filename = state.get('last_file', '')
        
        self.colors = []
        self.prev_colors = [] 
        self.show_prev = False 
        self.animating = False 
        
        self.angle_x = 0.5
        self.angle_y = 0.5
        self.angle_z = 0.0 
        self.fov = 400
        
        # 2D Screen Scale (New Requirement 6)
        self.screen_scale = state.get('screen_scale', 1.0)
        
        # Zoom (Viewer Distance)
        self.viewer_distance = state.get('viewer_distance', 2.66) # Default 1.5x zoom
        
        # Dot Diameter
        self.point_scale_factor = state.get('point_scale', 1.0)
        
        # Default Colorspace (Requirement 5)
        self.colorspace = state.get('colorspace', 'HSV')
        
        self.axis_labels = {
            "RGB":      ["Red (R)", "Blue (B)", "Green (G)"],
            "HSV":      ["Hue/Sat X", "Value (Intensity)", "Hue/Sat Z"],
            "CIELAB":   ["Green-Red (a)", "Lightness (L)", "Blue-Yellow (b)"],
            "LCH (Polar)": ["Chroma X", "Lightness (L)", "Chroma Z"],
            "Oklab":    ["Green-Red (a)", "Lightness (L)", "Blue-Yellow (b)"]
        }
        
        self.setup_ui()
        
        # Load previous file if exists
        if self.current_filename and os.path.exists(self.current_filename):
            self.load_gpl(self.current_filename)
        else:
            self.update_canvas()
            
        self.animate_loop()

    def setup_ui(self):
        toolbar = tk.Frame(self.root, bd=1, relief=tk.RAISED)
        toolbar.pack(side=tk.TOP, fill=tk.X)
        
        # Buttons Left
        btn_load = tk.Button(toolbar, text="Load .gpl", command=self.load_gpl_dialog)
        btn_load.pack(side=tk.LEFT, padx=5, pady=5)
        
        lbl_mode = tk.Label(toolbar, text="Color Space:")
        lbl_mode.pack(side=tk.LEFT, padx=5)
        
        self.mode_var = tk.StringVar(value=self.colorspace)
        modes = ["RGB", "HSV", "CIELAB", "LCH (Polar)", "Oklab"]
        opt_mode = tk.OptionMenu(toolbar, self.mode_var, *modes, command=self.change_mode)
        opt_mode.pack(side=tk.LEFT, padx=5)
        
        # Labels Center (Requirement 4)
        self.lbl_filename = tk.Label(toolbar, text=f"File: {os.path.basename(self.current_filename)}", fg="#aaaaaa")
        self.lbl_filename.pack(side=tk.LEFT, padx=10, expand=False) # expand=False to keep compact
        
        # Labels Right
        self.lbl_info = tk.Label(toolbar, text="Colors: 0", fg="gray")
        self.lbl_info.pack(side=tk.RIGHT, padx=10)
        
        self.canvas = tk.Canvas(self.root, bg="#202020")
        self.canvas.pack(fill=tk.BOTH, expand=True)
        
        self.canvas.bind("<ButtonPress-1>", self.on_mouse_down)
        self.canvas.bind("<B1-Motion>", self.on_mouse_drag)
        
        # Mouse Wheels (Requirement 6: Ctrl+Wheel for Screen Scale)
        self.canvas.bind("<Button-4>", self.on_mousewheel)
        self.canvas.bind("<Button-5>", self.on_mousewheel)
        self.canvas.bind("<MouseWheel>", self.on_mousewheel)
        
        # Keys
        self.root.bind('<p>', self.toggle_prev)
        self.root.bind('<r>', self.toggle_anim)
        
        self.canvas.bind("<Button-1>", lambda e: self.canvas.focus_set(), add="+")
        
        self.last_mouse_x = 0
        self.last_mouse_y = 0

    def save_prefs(self):
        state = {
            'last_file': self.current_filename,
            'viewer_distance': self.viewer_distance,
            'point_scale': self.point_scale_factor,
            'colorspace': self.colorspace,
            'screen_scale': self.screen_scale
        }
        save_state(state)

    def toggle_prev(self, event):
        self.show_prev = not self.show_prev
        self.update_canvas()

    def toggle_anim(self, event):
        self.animating = not self.animating

    def animate_loop(self):
        if self.animating:
            self.angle_y += math.radians(3)
            self.update_canvas()
        self.root.after(33, self.animate_loop)

    def on_mousewheel(self, event):
        # Linux: Button-4 (up), Button-5 (down). Win/Mac: delta.
        if event.num == 5 or event.delta < 0:
            delta = 1
        else:
            delta = -1
            
        state = event.state
        
        # Check modifiers (Shift: 0x0001, Ctrl: 0x0004)
        is_shift = (state & 1)
        is_ctrl = (state & 4)
        
        if is_ctrl:
            # Screen Scale (2D Zoom)
            self.screen_scale += delta * 0.1
            if self.screen_scale < 0.1: self.screen_scale = 0.1
            self.save_prefs() # Save state on change
        elif is_shift:
            # Point Size
            self.point_scale_factor += delta * 0.1
            if self.point_scale_factor < 0.1: self.point_scale_factor = 0.1
            self.save_prefs()
        else:
            # Viewport Zoom (Perspective)
            self.viewer_distance += delta * 0.2
            if self.viewer_distance < 1.0: self.viewer_distance = 1.0
            self.save_prefs()
            
        self.update_canvas()

    def load_gpl_dialog(self):
        # Determine initial dir
        start_dir = os.path.dirname(self.current_filename) if self.current_filename else None
        dlg = CustomFileDialog(self.root, initialdir=start_dir)
        if dlg.result:
            self.load_gpl(dlg.result)

    def load_gpl(self, path):
        if not os.path.exists(path):
            return

        raw_colors = []
        try:
            with open(path, "r") as f:
                lines = f.readlines()
                for line in lines:
                    line = line.strip()
                    if not line or line.startswith("GIMP") or line.startswith("Name:") or \
                       line.startswith("Columns:") or line.startswith("#"):
                        continue
                    
                    parts = line.split()
                    if len(parts) >= 3:
                        try:
                            r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
                            name = " ".join(parts[3:]) if len(parts) > 3 else "Untitled"
                            raw_colors.append((r, g, b, name))
                        except ValueError:
                            continue
        except Exception as e:
            messagebox.showerror("Error", f"Failed to read file:\n{e}")
            return

        self.prev_colors = self.colors
        self.current_filename = path
        self.lbl_filename.config(text=f"File: {os.path.basename(path)}")
        self.recalculate_points(raw_colors)
        self.lbl_info.config(text=f"Colors: {len(self.colors)}")
        self.save_prefs()
        self.update_canvas()

    def change_mode(self, value):
        self.colorspace = value
        self.mode_var.set(value)
        self.save_prefs()
        
        new_points = []
        for p in self.colors:
            r, g, b, name = p.color_info
            x, y, z = ColorConverter.get_coords(self.colorspace, r, g, b)
            new_points.append((x, y, z, p.color_info))
        self.colors = new_points
        
        new_prev_points = []
        for p in self.prev_colors:
            r, g, b, name = p.color_info
            x, y, z = ColorConverter.get_coords(self.colorspace, r, g, b)
            new_prev_points.append((x, y, z, p.color_info))
        self.prev_colors = new_prev_points
        
        self.update_canvas()

    def recalculate_points(self, raw_data):
        self.colors = []
        for r, g, b, name in raw_data:
            x, y, z = ColorConverter.get_coords(self.colorspace, r, g, b)
            self.colors.append((x, y, z, (r, g, b, name)))

    def on_mouse_down(self, event):
        self.last_mouse_x = event.x
        self.last_mouse_y = event.y

    def on_mouse_drag(self, event):
        dx = event.x - self.last_mouse_x
        dy = event.y - self.last_mouse_y
        
        self.angle_y += dx * 0.01
        self.angle_x += dy * 0.01
        
        self.last_mouse_x = event.x
        self.last_mouse_y = event.y
        self.update_canvas()

    def draw_cube(self, w, h):
        vertices = [
            (0,0,0), (1,0,0), (1,1,0), (0,1,0),
            (0,0,1), (1,0,1), (1,1,1), (0,1,1)
        ]
        
        proj_points = []
        cx, cy = self.angle_x, self.angle_y
        cz = self.angle_z
        
        for x, y, z in vertices:
            x, y, z = x-0.5, y-0.5, z-0.5
            x, y, z = rotate_all(x, y, z, cx, cy, cz)
            factor = self.fov / (self.viewer_distance + z)
            
            # Apply Screen Scale (Requirement 6)
            # Scale relative to center of screen
            px_raw = x * factor + w / 2
            py_raw = -y * factor + h / 2
            
            px = (px_raw - w/2) * self.screen_scale + w/2
            py = (py_raw - h/2) * self.screen_scale + h/2
            
            proj_points.append((px, py))
            
        edges = [
            (0,1,'red'), (1,2,'blue'),  (2,3,'red'), (3,0,'blue'),
            (4,5,'red'), (5,6,'blue'),  (6,7,'red'), (7,4,'blue'),
            (0,4,'green'), (1,5,'green'), (2,6,'green'), (3,7,'green')
        ]
        
        colors = {'red': '#ff4444', 'green': '#44ff44', 'blue': '#4444ff'}
        
        create_line = self.canvas.create_line
        for s, e, c_name in edges:
            x1, y1 = proj_points[s]
            x2, y2 = proj_points[e]
            create_line(x1, y1, x2, y2, fill=colors[c_name], width=2)

        labels = self.axis_labels.get(self.colorspace, ["", "", ""])
        info_str = f"AXIS MAPPING:\n"
        info_str += f"Red Line: {labels[0]}\n"
        info_str += f"Green Line: {labels[2]}\n"
        info_str += f"Blue Line: {labels[1]}"
        
        self.canvas.create_text(w - 10, 10, text=info_str, fill="#aaaaaa", 
                                anchor="ne", font=("Arial", 10))

        help_str = "CONTROLS:\n"
        help_str += "L-Click + Drag: Rotate\n"
        help_str += "Mouse Wheel: Zoom (Perspective)\n"
        help_str += "Shift+Wheel: Scale Dots\n"
        help_str += "Ctrl+Wheel: 2D Screen Scale\n"
        help_str += "Key 'p': Toggle Prev Palette\n"
        help_str += "Key 'r': Auto-Rotate"
        
        self.canvas.create_text(10, 10, text=help_str, fill="#aaaaaa", 
                                anchor="nw", font=("Arial", 9))

    def update_canvas(self):
        self.canvas.delete("all")
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        
        if w < 10 or h < 10:
            return

        self.draw_cube(w, h)
        
        render_list = []
        cx, cy, cz = self.angle_x, self.angle_y, self.angle_z
        fov = self.fov
        vd = self.viewer_distance
        whalf = w / 2
        hhalf = h / 2
        
        count = len(self.colors)
        density_scale = (100.0 / count) ** (1/3) if count > 0 else 1.0
        base_diameter = w / 80.0
        scale_factor = self.point_scale_factor * density_scale

        sources = [(self.colors, False)]
        if self.show_prev and self.prev_colors:
            sources.append((self.prev_colors, True))
            
        for source_list, is_prev in sources:
            for p in source_list:
                rx, ry, rz = p[0] - 0.5, p[1] - 0.5, p[2] - 0.5
                rx, ry, rz = rotate_all(rx, ry, rz, cx, cy, cz)
                
                factor = fov / (vd + rz)
                
                px_raw = rx * factor + whalf
                py_raw = -ry * factor + hhalf
                
                # Apply Screen Scale
                px = (px_raw - whalf) * self.screen_scale + whalf
                py = (py_raw - hhalf) * self.screen_scale + hhalf
                
                render_list.append((rz, px, py, factor, p[3], is_prev))
        
        render_list.sort(key=lambda x: x[0], reverse=True)
        
        create_oval = self.canvas.create_oval
        for _, px, py, scale, info, is_prev in render_list:
            r, g, b, name = info
            hex_col = f"#{r:02x}{g:02x}{b:02x}"
            
            normalized_size = base_diameter * (scale / 100.0) * scale_factor
            radius = max(1, normalized_size / 2)
            
            if is_prev:
                create_oval(px-radius, py-radius, px+radius, py+radius, 
                            fill="", outline=hex_col, width=1)
            else:
                create_oval(px-radius, py-radius, px+radius, py+radius, 
                            fill=hex_col, outline="")

if __name__ == "__main__":
    root = tk.Tk()
    app = PaletteViewer3D(root)
    root.mainloop()

