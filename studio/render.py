"""Turns a time range into a vertical clip: 9:16 layout, bouncy word captions, hook title, cover."""
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import config, roman
from .media import NO_WINDOW, run

W, H = config.OUT_W, config.OUT_H

# ASS colours are &HBBGGRR. `size` is the ASS font size (line height); _Font turns it into real pixels.
STYLES = {
    "bounce": {"label": "Bounce", "font": "Poppins ExtraBold", "size": 132, "base": "FFFFFF", "active": "00F0FF",
               "strong": "FFFFFF", "outline": 7, "pop": 112, "upper": True, "per": 3},
    "hype": {"label": "Hype", "font": "Anton", "size": 152, "base": "FFFFFF", "active": "3C3CFF",
             "strong": "00D7FF", "outline": 7, "pop": 114, "upper": True, "per": 2},
    "clean": {"label": "Clean", "font": "Poppins ExtraBold", "size": 100, "base": "FFFFFF", "active": "6BD7FF",
              "strong": "FFFFFF", "outline": 5, "pop": 106, "upper": False, "per": 4},
}
HOOK_STYLES = {
    "white": {"label": "White Box", "font": "Poppins ExtraBold", "size": 96, "ink": "14100E", "box": "FFFFFF", "pad_x": 36, "pad_y": 22, "radius": 26, "max_w": 900},
    "yellow": {"label": "Yellow Box", "font": "Poppins ExtraBold", "size": 96, "ink": "000000", "box": "00E5FF", "pad_x": 36, "pad_y": 22, "radius": 26, "max_w": 900},
    "black": {"label": "Dark Box", "font": "Poppins ExtraBold", "size": 96, "ink": "FFFFFF", "box": "14100E", "pad_x": 36, "pad_y": 22, "radius": 26, "max_w": 900},
    "red": {"label": "Red Box", "font": "Poppins ExtraBold", "size": 96, "ink": "FFFFFF", "box": "2020E6", "pad_x": 36, "pad_y": 22, "radius": 26, "max_w": 900},
    "outline": {"label": "Outline (No box)", "font": "Anton", "size": 110, "ink": "FFFFFF", "box": None, "outline": 8, "pad_x": 36, "pad_y": 22, "radius": 0, "max_w": 940},
}
HOOK = HOOK_STYLES["white"]
FONT_FILES = {"Poppins ExtraBold": "Poppins-ExtraBold.ttf", "Anton": "Anton-Regular.ttf", "Archivo Black": "ArchivoBlack-Regular.ttf"}
CAP_MAX_W = 960   # captions never run wider than this, whatever is said

EMOJI_PATTERN = re.compile(
    r"([\U00010000-\U0010ffff\u2600-\u26ff\u2700-\u27bf\ufe00-\ufe0f\u200d]+)"
)


def has_emoji(text: str) -> bool:
    return bool(EMOJI_PATTERN.search(str(text or "")))


def _bgr_to_rgb(bgr_hex: str) -> tuple:
    if not bgr_hex or len(bgr_hex) != 6:
        return (255, 255, 255)
    b, g, r = int(bgr_hex[0:2], 16), int(bgr_hex[2:4], 16), int(bgr_hex[4:6], 16)
    return (r, g, b)


def render_hook_image(hook: str, hook_style: str = "white", y: int = 300, max_w: int = 900):
    """Renders heading text and background box with full color emojis to a PIL Image."""
    from PIL import Image, ImageDraw, ImageFont
    cfg = HOOK_STYLES.get(hook_style, HOOK)
    font_file = FONT_FILES.get(cfg["font"], FONT_FILES["Poppins ExtraBold"])
    font_text_path = config.FONTS_DIR / font_file
    if not font_text_path.exists():
        font_text_path = Path(__file__).resolve().parent / "fonts" / font_file

    font_emj_paths = [
        Path("C:/Windows/Fonts/seguiemj.ttf"),
        Path("/System/Library/Fonts/Apple Color Emoji.ttc"),
        Path("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"),
    ]
    font_emj_path = next((p for p in font_emj_paths if p.exists()), None)

    f_metric = _Font.get(cfg["font"])
    base_em = max(36, int(round(f_metric.em(cfg["size"]))))
    size = base_em
    text_font = ImageFont.truetype(str(font_text_path), size)
    emj_font = ImageFont.truetype(str(font_emj_path), size) if font_emj_path else text_font

    words = hook.strip().split()
    if not words:
        return Image.new("RGBA", (W, H), (0, 0, 0, 0))

    def measure_line(line_str):
        parts = EMOJI_PATTERN.split(line_str)
        w = 0.0
        for p in parts:
            if not p:
                continue
            f = emj_font if EMOJI_PATTERN.match(p) else text_font
            w += f.getlength(p)
        return w

    full_line = " ".join(words)
    if measure_line(full_line) > max_w and len(words) > 1:
        cut = min(range(1, len(words)), key=lambda i: max(measure_line(" ".join(words[:i])), measure_line(" ".join(words[i:]))))
        lines = [" ".join(words[:cut]), " ".join(words[cut:])]
    else:
        lines = [full_line]

    widest = max(measure_line(l) for l in lines)
    if widest > max_w:
        scale = max_w / max(widest, 1.0)
        size = max(32, int(size * scale))
        text_font = ImageFont.truetype(str(font_text_path), size)
        emj_font = ImageFont.truetype(str(font_emj_path), size) if font_emj_path else text_font
        widest = max(measure_line(l) for l in lines)

    line_h = int(size * 1.25)
    total_text_h = len(lines) * line_h

    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)

    if cfg.get("box"):
        bw = widest + 2 * cfg["pad_x"]
        bh = total_text_h + 2 * cfg["pad_y"]
        x0 = (W - bw) / 2
        y0 = y - bh / 2
        x1 = x0 + bw
        y1 = y0 + bh
        r = min(cfg["radius"], bh / 2)
        box_rgb = _bgr_to_rgb(cfg["box"])
        draw.rounded_rectangle((x0, y0, x1, y1), radius=r, fill=box_rgb)

    start_y = y - total_text_h / 2
    ink_rgb = _bgr_to_rgb(cfg["ink"])
    outline_w = int(round(cfg.get("outline", 0) * size / max(cfg["size"], 1)))

    for i, line in enumerate(lines):
        line_w = measure_line(line)
        line_x = (W - line_w) / 2
        cur_y = start_y + i * line_h

        parts = EMOJI_PATTERN.split(line)
        cur_x = line_x
        for p in parts:
            if not p:
                continue
            is_emj = bool(EMOJI_PATTERN.match(p))
            f = emj_font if is_emj else text_font
            pw = f.getlength(p)
            if is_emj:
                draw.text((cur_x, cur_y), p, font=f, embedded_color=True)
            else:
                if outline_w > 0:
                    draw.text((cur_x, cur_y), p, font=f, fill=ink_rgb,
                              stroke_width=outline_w, stroke_fill=(0, 0, 0))
                else:
                    draw.text((cur_x, cur_y), p, font=f, fill=ink_rgb)
            cur_x += pw

    return im


class _Font:
    """Measures text exactly as the renderer will draw it, so every word can be placed by hand: the highlighted
    word can grow without pushing its neighbours, and the heading box fits its text."""
    _cache: dict = {}

    def __init__(self, name):
        import struct
        path = Path(__file__).resolve().parent / "fonts" / FONT_FILES.get(name, FONT_FILES["Poppins ExtraBold"])
        d = path.read_bytes()
        tables = {}
        for i in range(struct.unpack(">H", d[4:6])[0]):
            tag, _, off, _ = struct.unpack(">4sIII", d[12 + 16 * i: 28 + 16 * i])
            tables[tag] = off
        self.upm = struct.unpack(">H", d[tables[b"head"] + 18: tables[b"head"] + 20])[0]
        o = tables[b"OS/2"]
        self.asc, self.desc = struct.unpack(">HH", d[o + 74: o + 78])      # what the renderer sizes the font by
        self.cap = struct.unpack(">h", d[o + 88: o + 90])[0] or int(self.upm * 0.7)
        self.path = str(path)
        self._pil = {}

    @classmethod
    def get(cls, name):
        if name not in cls._cache:
            cls._cache[name] = cls(name)
        return cls._cache[name]

    def em(self, size):
        return size * self.upm / (self.asc + self.desc)

    def width(self, text, size):
        """Pixels wide at this ASS size."""
        try:
            from PIL import ImageFont
            if "f" not in self._pil:
                self._pil["f"] = ImageFont.truetype(self.path, 200)
            return self._pil["f"].getlength(text) * self.em(size) / 200
        except Exception:  # noqa: BLE001 - no measuring library: a fair estimate keeps clips rendering
            return len(text) * self.em(size) * 0.62

    def cap_shift(self, size):
        """How far below the anchor the middle of a capital letter sits when text is centred on a point."""
        return ((self.asc - self.desc) / 2 - self.cap / 2) * size / (self.asc + self.desc)


CAPTION_LEAD = 0.0  # measured: word stamps are within 0.15 s of the voice, so no shift is needed
def install_fonts():
    """Copy the bundled caption fonts next to the data, so captions look the same on every machine and server."""
    src = Path(__file__).resolve().parent / "fonts"
    for f in src.glob("*.ttf"):
        if not (config.FONTS_DIR / f.name).exists():
            shutil.copyfile(f, config.FONTS_DIR / f.name)


LAYOUTS = {"blur": "Full frame + blurred fill", "zoom": "Zoomed in + blurred fill", "crop": "Fill the screen (centre crop)",
           "left": "Fill the screen, keep the left side", "right": "Fill the screen, keep the right side",
           "fit": "Full frame on black", "split": "Split screen: left half on top, right half below (two people)",
           "gameplay": "Gameplay fills the screen, facecam in the corner",
           "splitscreen": "Gaming split: facecam on top, gameplay below",
           "custom": "Custom layout: user-defined framing"}
_FILLS = ("crop", "left", "right", "gameplay")      # layouts where the picture covers the whole frame


def _ts(t):
    t = max(0.0, t)
    h, m = int(t // 3600), int(t % 3600 // 60)
    return f"{h}:{m:02d}:{t % 60:05.2f}"


def _clean(text):
    return re.sub(r"[\x00-\x1f\x7f]+", " ", re.sub(r"[{}\\]", "", str(text))).strip()


def _key(word):
    return re.sub(r"[^a-z0-9']", "", word.lower())


def _groups(words, per):
    out, cur = [], []
    for w in words:
        if cur and (len(cur) >= per or sum(len(x["w"]) for x in cur) + len(w["w"]) > 16
                    or w["s"] - cur[-1]["e"] > 0.45 or cur[-1]["w"][-1:] in ".?!"):
            out.append(cur)
            cur = []
        cur.append(w)
    if cur:
        out.append(cur)
    return out


def geometry(src_w, src_h, layout):
    """Where the video sits in the 1080x1920 frame, and where hook and captions go."""
    if src_h >= src_w and layout != "crop":
        layout = "crop"  # already vertical or square: nothing to gain from a blurred fill
    if layout not in LAYOUTS:
        layout = "blur"
    if layout in ("blur", "fit"):
        fg_h = min(H, int(round(W * src_h / src_w / 2)) * 2)
    elif layout == "zoom":
        fg_h = 1000
    else:
        fg_h = H
    top = (H - fg_h) // 2
    if layout in _FILLS:
        return layout, fg_h, 300, 1380
    if layout in ("splitscreen", "custom"):
        return layout, H, 200, H // 2
    if layout == "split":
        return layout, fg_h, 230, H // 2        # captions sit on the line between the two people
    return layout, fg_h, max(230, top - 190), min(1640, top + fg_h + 180)


def _hook_events(hook, dur, y, hook_style="white"):
    """The heading: styled text in a rounded box or outline on one line or two balanced ones."""
    cfg = HOOK_STYLES.get(hook_style, HOOK)
    f, size = _Font.get(cfg["font"]), cfg["size"]
    words = hook.split()
    if not words:
        return []
    lines = [" ".join(words)]
    if f.width(lines[0], size) > cfg["max_w"] and len(words) > 1:      # two lines, split where they come out most even
        cut = min(range(1, len(words)), key=lambda i: max(f.width(" ".join(words[:i]), size), f.width(" ".join(words[i:]), size)))
        lines = [" ".join(words[:cut]), " ".join(words[cut:])]
    widest = max(f.width(l, size) for l in lines)
    if widest > cfg["max_w"]:
        size = max(40, int(size * cfg["max_w"] / widest))
        widest = max(f.width(l, size) for l in lines)
    line_h = f.em(size) * 1.16
    span = f"{_ts(0)},{_ts(dur)}"
    ev = []
    if cfg.get("box"):
        bw, bh = widest + 2 * cfg["pad_x"], line_h * len(lines) + 2 * cfg["pad_y"]
        x0, y0, r = (W - bw) / 2, y - bh / 2, min(cfg["radius"], bh / 2)
        x1, y1 = x0 + bw, y0 + bh
        n = lambda v: f"{v:.0f}"                                                         # noqa: E731
        box = (f"m {n(x0 + r)} {n(y0)} l {n(x1 - r)} {n(y0)} b {n(x1)} {n(y0)} {n(x1)} {n(y0)} {n(x1)} {n(y0 + r)} "
               f"l {n(x1)} {n(y1 - r)} b {n(x1)} {n(y1)} {n(x1)} {n(y1)} {n(x1 - r)} {n(y1)} "
               f"l {n(x0 + r)} {n(y1)} b {n(x0)} {n(y1)} {n(x0)} {n(y1)} {n(x0)} {n(y1 - r)} "
               f"l {n(x0)} {n(y0 + r)} b {n(x0)} {n(y0)} {n(x0)} {n(y0)} {n(x0 + r)} {n(y0)}")
        ev.append(f"Dialogue: 3,{span},Hook,,0,0,0,,{{\\an7\\pos(0,0)\\fad(160,0)\\c&H{cfg['box']}&\\p1}}{box}{{\\p0}}")
    outline = cfg.get("outline", 0)
    out_tag = f"\\bord{outline}\\3c&H000000&" if outline else "\\bord0"
    for i, line in enumerate(lines):
        cy = y - line_h * (len(lines) - 1) / 2 + i * line_h - f.cap_shift(size)
        ev.append(f"Dialogue: 4,{span},Hook,,0,0,0,,{{\\an5\\pos({W // 2},{cy:.0f})\\fad(160,0)\\c&H{cfg['ink']}&\\fs{size}{out_tag}}}{line}")
    return ev


def build_ass(words, start, end, hook, style_name, highlight, hook_y, cap_y, hook_style="white", handle=None, handle_pos="top_right") -> str:
    st = STYLES.get(style_name, STYLES["bounce"])
    hk = HOOK_STYLES.get(hook_style, HOOK)
    words = [dict(w, s=w["s"] - CAPTION_LEAD, e=w["e"] - CAPTION_LEAD) for w in words]
    strong = {_key(h) for h in highlight if _key(h)}
    outline_val = hk.get("outline", 0)
    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{st['font']},{st['size']},&H00{st['base']},&H00{st['base']},&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,{st['outline']},0,5,0,0,0,1
Style: Hook,{hk['font']},{hk['size']},&H00{hk['ink']},&H00{hk['ink']},&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,{outline_val},0,5,0,0,0,1
Style: Handle,Poppins ExtraBold,42,&H00FFFFFF,&H00FFFFFF,&H00000000,&H70000000,-1,0,0,0,100,100,0,0,1,3,2,5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    dur = end - start
    if has_emoji(hook):
        ev = []
    else:
        ev = _hook_events(_clean(hook), dur, hook_y, hook_style=hook_style)
    if handle and str(handle).strip():
        h_text = _clean(str(handle).strip())
        h_pos = str(handle_pos or "top_right").lower().replace("-", "_")
        pos_map = {
            "top_right": (9, 1030, 60),
            "top_left": (7, 50, 60),
            "top_center": (8, 540, 60),
            "bottom_right": (3, 1030, 1850),
            "bottom_left": (1, 50, 1850),
            "bottom_center": (2, 540, 1850),
            "below_cam": (8, 540, 980),
        }
        an, hx, hy = pos_map.get(h_pos, (9, 1030, 60))
        span = f"{_ts(0)},{_ts(dur)}"
        ev.append(f"Dialogue: 0,{span},Handle,,0,0,0,,{{\\an{an}\\pos({hx},{hy})\\fad(180,180)\\bord3\\shad2\\fs42}}{h_text}")
    f = _Font.get(st["font"])
    inside = [dict(w, w=_clean(w["w"])) for w in words if w["s"] >= start - 0.05 and w["s"] < end]
    inside = sorted((w for w in inside if w["w"]), key=lambda w: w["s"])
    for i, w in enumerate(inside[:-1]):
        w["e"] = max(w["s"], min(w["e"], inside[i + 1]["s"]))
    groups = _groups(inside, st["per"])
    for gi, g in enumerate(groups):
        g_start = max(0.0, g[0]["s"] - start)
        g_end = min(g[-1]["e"] + 0.25, groups[gi + 1][0]["s"] if gi + 1 < len(groups) else end) - start
        if g_end - g_start < 0.02:
            continue
        texts = []
        for x in g:
            t = re.sub(r"[.,;:]+$", "", x["w"])
            texts.append(t.upper() if st["upper"] else t)
        if not all(roman.drawable(t) for t in texts):
            # A script the caption font cannot draw (Japanese, Thai, Chinese...): its words cannot be measured, so
            # they are not placed one by one. The line is drawn whole and centred, in a font the system has for it.
            line = " ".join(texts)
            fs = max(44, min(int(st["size"] * 0.7), int(1500 / max(1, len(line)) * 1.6)))
            ev.append(f"Dialogue: 1,{_ts(g_start)},{_ts(g_end)},Cap,,60,60,0,,{{\\an5\\pos({W // 2},{cap_y:.0f})\\q0\\fs{fs}}}{line}")
            continue
        size = st["size"]
        gap = f.width("n n", size) - 2 * f.width("n", size) + (2 * st["outline"] + 6) * size / st["size"]   # a space, plus room for both outlines
        total = sum(f.width(t, size) for t in texts) + gap * (len(texts) - 1)
        if total > CAP_MAX_W:                                  # a long phrase: shrink it to fit, never run off the frame
            size = max(36, int(size * CAP_MAX_W / total))
            gap = f.width("n n", size) - 2 * f.width("n", size) + (2 * st["outline"] + 6) * size / st["size"]   # a space, plus room for both outlines
            total = sum(f.width(t, size) for t in texts) + gap * (len(texts) - 1)
        cy = cap_y - f.cap_shift(size)
        x = (W - total) / 2
        p = st["pop"]
        for i, (w, t) in enumerate(zip(g, texts)):
            wd = f.width(t, size)
            p = max(104, min(st["pop"], 100 + int(2200 / max(wd, 1))))   # long words grow less, so they never touch their neighbours
            pos = f"\\an5\\pos({x + wd / 2:.0f},{cy:.0f})\\fs{size}"
            x += wd + gap
            a = max(g_start, w["s"] - start)
            b = (g[i + 1]["s"] - start) if i + 1 < len(g) else g_end
            base = st["strong"] if _key(w["w"]) in strong else st["base"]
            if a - g_start >= 0.02:                                                   # waiting to be said
                ev.append(f"Dialogue: 1,{_ts(g_start)},{_ts(a)},Cap,,0,0,0,,{{{pos}\\c&H{base}&}}{t}")
            if b - a >= 0.02:                                                         # being said: colour and a quick pop, in front
                ev.append(f"Dialogue: 2,{_ts(a)},{_ts(b)},Cap,,0,0,0,,{{{pos}\\c&H{st['active']}&\\fscx94\\fscy94"
                          f"\\t(0,90,\\fscx{p}\\fscy{p})\\t(90,200,\\fscx{p - 5}\\fscy{p - 5})}}{t}")
            if g_end - b >= 0.02:                                                     # said
                ev.append(f"Dialogue: 1,{_ts(b)},{_ts(g_end)},Cap,,0,0,0,,{{{pos}\\c&H{base}&\\fscx{p - 5}\\fscy{p - 5}"
                          f"\\t(0,90,\\fscx100\\fscy100)}}{t}")
    return head + "\n".join(ev) + "\n"


PIP_W = 380            # how wide the facecam is in the 1080-wide frame
PIP_MARGIN = 26


def _filter(layout, fg_h, facecam=None, custom_layout=None, src_w=1920, src_h=1080):
    if custom_layout is None:
        custom_layout = {}
    
    fx, fy, fw, fh = 0, 0, 0, 0
    if facecam and len(facecam) == 4 and int(facecam[2]) > 8 and int(facecam[3]) > 8:
        fx, fy, fw, fh = (int(v) for v in facecam)
    elif facecam in ("right", "bottom-right"):
        fx, fy, fw, fh = int(src_w * 0.75), int(src_h * 0.54), int(src_w * 0.24), int(src_h * 0.44)
    elif facecam in ("bottom-left", "left"):
        fx, fy, fw, fh = int(src_w * 0.01), int(src_h * 0.54), int(src_w * 0.24), int(src_h * 0.44)
    elif facecam in ("top-left",):
        fx, fy, fw, fh = int(src_w * 0.01), int(src_h * 0.02), int(src_w * 0.24), int(src_h * 0.44)
    elif facecam in ("top-right",):
        fx, fy, fw, fh = int(src_w * 0.75), int(src_h * 0.02), int(src_w * 0.24), int(src_h * 0.44)
    has_cam = fw > 8 and fh > 8

    if layout == "gameplay" and has_cam:
        pip_h = max(2, int(round(PIP_W * fh / fw)))
        return (f"[0:v]fps={config.OUT_FPS},split=2[base][fc];"
                f"[base]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1[b];"
                f"[fc]crop={fw}:{fh}:{fx}:{fy},scale={PIP_W}:{pip_h},setsar=1[p];"
                f"[b][p]overlay={W - PIP_W - PIP_MARGIN}:{PIP_MARGIN}[v0];")

    fill = f"[0:v]fps={config.OUT_FPS},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}"
    if layout == "crop" or (layout == "gameplay" and not has_cam):
        return fill + ",setsar=1[v0];"
    if layout == "left":
        return fill + ":0:0,setsar=1[v0];"
    if layout == "right":
        return fill + ":in_w-out_w:0,setsar=1[v0];"
    if layout == "fit":
        return f"[0:v]fps={config.OUT_FPS},scale={W}:{fg_h},pad={W}:{H}:0:(oh-ih)/2:black,setsar=1[v0];"
    if layout == "split":
        half = f"scale={W}:{H // 2}:force_original_aspect_ratio=increase,crop={W}:{H // 2}"
        return (f"[0:v]fps={config.OUT_FPS},split=2[l][r];[l]crop=iw/2:ih:0:0,{half}[t];"
                f"[r]crop=iw/2:ih:iw/2:0,{half}[u];[t][u]vstack,setsar=1[v0];")

    if layout in ("splitscreen", "custom"):
        if not has_cam:
            fx, fy, fw, fh = int(src_w * 0.01), int(src_h * 0.54), int(src_w * 0.24), int(src_h * 0.44)

        cam_pos = custom_layout.get("cam_pos", "top")
        split_pct = float(custom_layout.get("split_ratio", 50)) / 100.0 if layout == "custom" else 0.50
        split_pct = max(0.25, min(0.75, split_pct))
        cam_h = int(round(H * split_pct / 2)) * 2
        game_h = H - cam_h

        # PIP custom modes
        if layout == "custom" and cam_pos.startswith("pip_"):
            corner = cam_pos[4:]
            pw = int(custom_layout.get("pip_w", PIP_W))
            ph = max(2, int(round(pw * fh / fw)))
            px = W - pw - PIP_MARGIN if "r" in corner else PIP_MARGIN
            py = H - ph - PIP_MARGIN - 80 if "b" in corner else PIP_MARGIN + 50
            return (f"[0:v]fps={config.OUT_FPS},split=2[base][fc];"
                    f"[base]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1[b];"
                    f"[fc]crop={fw}:{fh}:{fx}:{fy},scale={pw}:{ph},setsar=1[p];"
                    f"[b][p]overlay={px}:{py}[v0];")

        cam_fit = custom_layout.get("cam_fit", "fit") if layout == "custom" else "fit"
        if cam_fit == "fill":
            cam_str = f"[v_cam]crop={fw}:{fh}:{fx}:{fy},scale={W}:{cam_h}:force_original_aspect_ratio=increase,crop={W}:{cam_h},setsar=1[cam];"
        else:
            cam_str = (f"[v_cam]crop={fw}:{fh}:{fx}:{fy},split=2[c_fg][c_bg];"
                       f"[c_bg]scale={W}:{cam_h}:force_original_aspect_ratio=increase,crop={W}:{cam_h},boxblur=25:5,eq=brightness=-0.22[bg];"
                       f"[c_fg]scale={W}:{cam_h}:force_original_aspect_ratio=decrease[fg];"
                       f"[bg][fg]overlay=(W-w)/2:({cam_h}-h)/2[cam];")

        # Check if user specified a custom gameplay crop box [gx, gy, gw, gh]
        g_box = custom_layout.get("gameplay_box")
        if g_box and len(g_box) == 4 and int(g_box[2]) > 8 and int(g_box[3]) > 8:
            gx, gy, gw, gh = (int(v) for v in g_box)
            game_str = f"[v_game]crop={gw}:{gh}:{gx}:{gy},scale={W}:{game_h}:force_original_aspect_ratio=increase,crop={W}:{game_h},setsar=1[game];"
        else:
            game_crop = custom_layout.get("game_crop", "auto") if layout == "custom" else "auto"
            if game_crop == "left":
                game_x = "0"
            elif game_crop == "right":
                game_x = "iw-out_w"
            elif game_crop == "center":
                game_x = "(iw-out_w)/2"
            else:
                if fx < W * 0.35:
                    game_x = "(iw-out_w)*0.85"
                elif fx > W * 0.65:
                    game_x = "(iw-out_w)*0.15"
                else:
                    game_x = "(iw-out_w)/2"

            game_str = f"[v_game]scale={W}:{game_h}:force_original_aspect_ratio=increase,crop={W}:{game_h}:{game_x}:0,setsar=1[game];"

        if cam_pos == "bottom" and layout == "custom":
            stack = f"[game][cam]vstack=inputs=2,drawbox=x=0:y={game_h - 4}:w={W}:h=8:color=0x1E1612@1:t=fill,setsar=1[v0];"
        else:
            stack = f"[cam][game]vstack=inputs=2,drawbox=x=0:y={cam_h - 4}:w={W}:h=8:color=0x1E1612@1:t=fill,setsar=1[v0];"

        return f"[0:v]setpts=PTS-STARTPTS,fps={config.OUT_FPS},split=2[v_cam][v_game];" + cam_str + game_str + stack

    return (f"[0:v]fps={config.OUT_FPS},split=2[a][b];"
            f"[a]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=6:2,"
            f"scale={W}:{H},eq=brightness=-0.14:saturation=1.15[bg];"
            f"[b]scale={W}:{fg_h}:force_original_aspect_ratio=increase,crop={W}:{fg_h}[fg];"
            f"[bg][fg]overlay=0:(H-h)/2,setsar=1[v0];")


def _hook_y(layout, hook_y, facecam=None, custom_layout=None):
    """Where the heading goes. In the gameplay layout the webcam sits in the top corner, so a heading
    across the top would run under it: it goes just below the picture instead."""
    if layout in ("splitscreen", "custom"):
        return 200
    if layout == "gameplay" and facecam and len(facecam) == 4 and facecam[2] > 8:
        return PIP_MARGIN + int(round(PIP_W * facecam[3] / facecam[2])) + 32
    return hook_y


_qsv_ok = None
RENDER_SECONDS = 600      # one clip's video encode; far beyond normal, so a frozen encoder is stopped, not waited on


SFX_MAP = {
    "shock": "vine_boom.wav",
    "rage": "vine_boom.wav",
    "fail": "sad_trombone.wav",
    "clutch": "bass_drop.wav",
    "hype": "airhorn.wav",
    "funny": "rimshot.wav",
    "cringe": "record_scratch.wav",
    "awkward": "crickets.wav",
    "suspense": "heartbeat.wav",
}


def render_clip(src: Path, out_dir: Path, name: str, clip: dict, words: list, src_w: int, src_h: int) -> dict:
    """Writes <name>.mp4, <name>.jpg and <name>.ass into out_dir. Returns file names."""
    src = Path(src).resolve()
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    start, end = clip["start"], clip["end"]
    if words and not clip.get("manual_trim"):
        inside_w = [w for w in words if w["s"] >= start - 0.2 and w["e"] <= end + 0.2]
        if inside_w:
            first_w = inside_w[0]["s"]
            last_w = inside_w[-1]["e"]
            if first_w - start > 0.8:
                start = round(max(start, first_w - 0.25), 2)
            if end - last_w > 1.4:
                end = round(min(end, last_w + 0.4), 2)
    layout, fg_h, hook_y, cap_y = geometry(src_w, src_h, clip.get("layout", "blur"))
    face = clip.get("facecam")
    if layout == "gameplay" and not (face and len(face) == 4):
        layout = "crop"     # no webcam found: the game fills the screen, which is still the right shape
    custom_layout = clip.get("custom_layout") or {}
    hook_y = _hook_y(layout, hook_y, face, custom_layout=custom_layout)
    handle = clip.get("handle")
    handle_pos = clip.get("handle_pos", "top_right")
    ass = build_ass(words if clip.get("captions", True) else [], start, end, clip.get("hook", ""), clip.get("style", "bounce"),
                    clip.get("highlight_words", []), hook_y, cap_y, hook_style=clip.get("hook_style", "white"),
                    handle=handle, handle_pos=handle_pos)
    # The clip is made in a short work folder and moved into place afterwards. The caption step of ffmpeg cannot
    # open files whose full path is longer than 260 characters on Windows, which a data folder deep inside other
    # folders easily reaches. Inside the work folder every name is short and relative (a drive colon would also
    # break the filter syntax).
    work = Path(tempfile.mkdtemp(prefix="pk"))
    try:
        hook_img = None
        if has_emoji(clip.get("hook", "")):
            hook_im = render_hook_image(clip.get("hook", ""), hook_style=clip.get("hook_style", "white"), y=hook_y)
            hook_img = work / f"{name}.hook.png"
            hook_im.save(hook_img, format="PNG")
        # The title and description are also written into the file itself, for any place that reads them from it.
        meta = {"title": clip.get("title") or "", "description": clip.get("description") or "", "comment": clip.get("description") or ""}
        return _render_in(work, src, out_dir, name, start, end, layout, fg_h, ass, face=face, meta=meta,
                          sfx=clip.get("sfx") or clip.get("meme"),
                          category=clip.get("category"),
                          flash=clip.get("flash", False),
                          music=clip.get("music"),
                          hook_img=hook_img,
                          custom_layout=custom_layout,
                          src_w=src_w, src_h=src_h)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def burn_subtitles(base_mp4: Path, ass_file: Path, out_mp4: Path, out_jpg: Path, vf_extra="", meta=None, hook_img: Path = None):
    """Burns ASS subtitles quickly onto a pre-rendered clean vertical clip (base_mp4) and extracts cover."""
    global _qsv_ok
    base_mp4 = base_mp4.resolve()
    ass_file = ass_file.resolve()
    out_mp4 = out_mp4.resolve()
    out_jpg = out_jpg.resolve()
    if hook_img:
        hook_img = hook_img.resolve()
    work = Path(tempfile.mkdtemp(prefix="pkburn"))
    try:
        shutil.copyfile(ass_file, work / ass_file.name)
        (work / "f").mkdir(exist_ok=True)
        for f in config.FONTS_DIR.glob("*.ttf"):
            shutil.copyfile(f, work / "f" / f.name)
        win_emj = Path("C:/Windows/Fonts/seguiemj.ttf")
        if win_emj.exists() and not (work / "f" / "seguiemj.ttf").exists():
            try:
                shutil.copyfile(win_emj, work / "f" / "seguiemj.ttf")
            except OSError:
                pass

        if hook_img and hook_img.is_file():
            shutil.copyfile(hook_img, work / "hook.png")
            fc = f"[0:v]ass={ass_file.name}:fontsdir=f{vf_extra}[vsub];[vsub][1:v]overlay=0:0[v0]"
            cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(base_mp4), "-i", str(work / "hook.png"),
                   "-filter_complex", fc, "-map", "[v0]", "-map", "0:a?", "-c:a", "copy"]
        else:
            cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(base_mp4),
                   "-vf", f"ass={ass_file.name}:fontsdir=f{vf_extra}",
                   "-c:a", "copy"]
        for k, v in (meta or {}).items():
            if v:
                cmd += ["-metadata", f"{k}={v}"]
        cmd += ["-movflags", "+faststart", "-pix_fmt"]
        encoders = [
            ("x264", ["yuv420p", "-c:v", "libx264", "-crf", "21", "-preset", "ultrafast"]),
        ]
        err = None
        for label, enc in encoders:
            try:
                p = subprocess.run(cmd + enc + [str(work / out_mp4.name)], cwd=work, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", creationflags=NO_WINDOW, timeout=120)
                if p.returncode == 0:
                    break
                err = p.stderr[-1200:]
            except subprocess.TimeoutExpired:
                err = f"{label} encoding timed out"
        else:
            raise RuntimeError(f"Burn failed: {err}")
        run(["ffmpeg", "-y", "-v", "error", "-ss", "1.0", "-i", str(work / out_mp4.name), "-frames:v", "1",
             "-q:v", "3", str(work / out_jpg.name)], cwd=work)
        shutil.move(str(work / out_mp4.name), str(out_mp4))
        shutil.move(str(work / out_jpg.name), str(out_jpg))
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _render_in(work: Path, src: Path, out_dir: Path, name: str, start, end, layout, fg_h, ass: str, face=None, meta=None,
               sfx=None, category=None, flash=False, music=None, hook_img=None, custom_layout=None, src_w=1920, src_h=1080) -> dict:
    global _qsv_ok
    (work / f"{name}.ass").write_text(ass, encoding="utf-8")
    (work / "f").mkdir()
    for f in config.FONTS_DIR.glob("*.ttf"):
        shutil.copyfile(f, work / "f" / f.name)
    sfx_dir = Path(__file__).resolve().parent / "sfx"
    whoosh = sfx_dir / "whoosh.wav"
    punch_sfx = None
    if sfx:
        t_name = sfx if str(sfx).endswith(".wav") else f"{sfx}.wav"
        if (sfx_dir / t_name).exists():
            punch_sfx = sfx_dir / t_name
    if not punch_sfx and category:
        mapped = SFX_MAP.get(str(category).lower())
        if mapped and (sfx_dir / mapped).exists():
            punch_sfx = sfx_dir / mapped
    if not punch_sfx or not punch_sfx.exists():
        punch_sfx = sfx_dir / "impact.wav"
    dur = end - start
    sfx_inputs = []
    if whoosh.exists() and punch_sfx.exists() and dur >= 3.0:
        sfx_inputs = ["-i", str(whoosh), "-i", str(punch_sfx)]
        # Place impact SFX at the climax/payoff (around 68% of clip or 1.2s before end)
        impact_ms = int(min(dur - 0.8, max(1.8, dur * 0.68)) * 1000)
        impact_sec = impact_ms / 1000.0

        music_bed = sfx_dir / f"bed_{music}.wav" if music else None
        if music_bed and music_bed.exists():
            sfx_inputs += ["-stream_loop", "-1", "-i", str(music_bed)]
            af_sfx = (f"[0:a:0]aresample=async=1:first_pts=0,asetpts=PTS-STARTPTS,volume=1.0[a0];"
                      f"[1:a]adelay=100|100,volume=0.65[sfx0];"
                      f"[2:a]adelay={impact_ms}|{impact_ms},volume=0.95[sfx1];"
                      f"[3:a]volume=0.08[sfx2];"
                      f"[a0][sfx0][sfx1][sfx2]amix=inputs=4:duration=first:dropout_transition=2:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[aout]")
        else:
            af_sfx = (f"[0:a:0]aresample=async=1:first_pts=0,asetpts=PTS-STARTPTS,volume=1.0[a0];"
                      f"[1:a]adelay=100|100,volume=0.65[sfx0];"
                      f"[2:a]adelay={impact_ms}|{impact_ms},volume=0.95[sfx1];"
                      f"[a0][sfx0][sfx1]amix=inputs=3:duration=first:dropout_transition=2:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[aout]")

        vf_extra = ""
        if flash or str(category).lower() in ("shock", "rage", "clutch"):
            vf_extra = f",drawbox=x=0:y=0:w=iw:h=ih:color=white@0.25:t=fill:enable='between(t,{impact_sec:.3f},{impact_sec + 0.07:.3f})'"

        fc_base = _filter(layout, fg_h, face, custom_layout=custom_layout, src_w=src_w, src_h=src_h) + af_sfx
        map_a = ["-map", "[aout]"]
    else:
        vf_extra = ""
        fc_base = _filter(layout, fg_h, face, custom_layout=custom_layout, src_w=src_w, src_h=src_h) + "[0:a:0]aresample=async=1:first_pts=0,asetpts=PTS-STARTPTS,loudnorm=I=-14:TP=-1.5:LRA=11[aout]"
        map_a = ["-map", "[aout]"]

    base = ["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.2f}", "-t", f"{dur:.2f}", "-avoid_negative_ts", "make_zero", "-i", str(src)] + sfx_inputs + [
            "-filter_complex", fc_base, "-map", "[v0]"] + map_a + [
            "-c:a", "aac", "-b:a", "160k", "-ar", "48000"]
    for k, v in (meta or {}).items():
        if v:
            base += ["-metadata", f"{k}={v}"]
    base += ["-movflags", "+faststart", "-pix_fmt"]
    encoders = []
    if _qsv_ok is not False:
        encoders.append(("qsv", ["nv12", "-c:v", "h264_qsv", "-global_quality", "23", "-preset", "fast"]))
    encoders.append(("x264", ["yuv420p", "-c:v", "libx264", "-crf", "21", "-preset", "veryfast"]))
    err = None
    for label, enc in encoders:
        p = subprocess.run(base + enc + [f"{name}.base.mp4"], cwd=work, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", creationflags=NO_WINDOW, timeout=RENDER_SECONDS)
        if p.returncode == 0:
            if label == "qsv":
                _qsv_ok = True
            break
        err = p.stderr[-1200:]
        if label == "qsv":
            _qsv_ok = False
    else:
        raise RuntimeError(f"Render failed: {err}")

    burn_subtitles(work / f"{name}.base.mp4", work / f"{name}.ass", work / f"{name}.mp4", work / f"{name}.jpg",
                   vf_extra=vf_extra, meta=meta, hook_img=hook_img)
    for ext in ("mp4", "base.mp4", "jpg", "ass", "hook.png"):
        if (work / f"{name}.{ext}").exists():
            shutil.move(str(work / f"{name}.{ext}"), str(out_dir / f"{name}.{ext}"))
    out_dict = {"file": f"{name}.mp4", "cover": f"{name}.jpg", "layout": layout}
    try:
        from . import qc
        qc_res = qc.check_clip(out_dir / f"{name}.mp4")
        if qc_res:
            out_dict["qc"] = qc_res
    except Exception:
        pass
    return out_dict
