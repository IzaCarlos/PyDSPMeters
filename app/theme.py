"""
Theme system for PyDSPMeters.
Supports multiple switchable theme presets and Qt stylesheet generation.
"""

from PySide6.QtGui import QColor, QFont
from PySide6.QtCore import Qt
import re



THEME_PRESETS = {
    "Midnight": {
        "BG_DARKEST": "#08080f", "BG_DARK": "#0e0e1a", "BG_MODULE": "#131320",
        "BG_HEADER": "#181830", "BG_SETTINGS": "#1a1a2e", "BG_INPUT": "#10101e",
        "BG_BADGE": "#1a1a35", "BG_BADGE_ALPHA": 180,
        "BORDER": "#252545", "BORDER_ACCENT": "#3a3a6a",
        "ACCENT": "#00d4ff", "ACCENT_DIM": "#0088aa",
        "ACCENT_PURPLE": "#7c4dff", "ACCENT_PINK": "#ff4da6",
        "TEXT": "#d8d8f0", "TEXT_DIM": "#7878a0", "TEXT_BRIGHT": "#f0f0ff",
        "BAND_LOW": "#0088ff", "BAND_MID": "#00e87b", "BAND_HIGH": "#ff4444",
        "METER_LOW": "#0088ff", "METER_MID": "#00e87b", "METER_HIGH": "#ff4444",
        "PEAK_LED": "#ffcc00", "CLIP_LED": "#ff2244",
        "HEATMAP_STOPS": [
            (0.00, "#000000"), (0.15, "#0a0040"), (0.30, "#0044cc"),
            (0.45, "#00bbcc"), (0.55, "#00cc44"), (0.70, "#cccc00"),
            (0.85, "#cc4400"), (1.00, "#ff0000")
        ]
    },
    "Abyss": {
        "BG_DARKEST": "#000000", "BG_DARK": "#0a0a0a", "BG_MODULE": "#0f0f0f",
        "BG_HEADER": "#161616", "BG_SETTINGS": "#1a1a1a", "BG_INPUT": "#0c0c0c",
        "BG_BADGE": "#111111", "BG_BADGE_ALPHA": 180,
        "BORDER": "#2a2a2a", "BORDER_ACCENT": "#3a3a3a",
        "ACCENT": "#e0e0e0", "ACCENT_DIM": "#808080",
        "ACCENT_PURPLE": "#9a9a9a", "ACCENT_PINK": "#c0c0c0",
        "TEXT": "#d0d0d0", "TEXT_DIM": "#666666", "TEXT_BRIGHT": "#ffffff",
        "BAND_LOW": "#666666", "BAND_MID": "#aaaaaa", "BAND_HIGH": "#ffffff",
        "METER_LOW": "#666666", "METER_MID": "#aaaaaa", "METER_HIGH": "#ffffff",
        "PEAK_LED": "#cccccc", "CLIP_LED": "#ffffff",
        "HEATMAP_STOPS": [
            (0.00, "#000000"), (0.30, "#222222"), (0.60, "#666666"),
            (0.85, "#aaaaaa"), (1.00, "#ffffff")
        ]
    },
    "Neon": {
        "BG_DARKEST": "#050a05", "BG_DARK": "#0a120a", "BG_MODULE": "#0e180e",
        "BG_HEADER": "#122012", "BG_SETTINGS": "#162816", "BG_INPUT": "#0a100a",
        "BG_BADGE": "#0e2a18", "BG_BADGE_ALPHA": 180,
        "BORDER": "#1a3a1a", "BORDER_ACCENT": "#2a5a2a",
        "ACCENT": "#00ff88", "ACCENT_DIM": "#009950",
        "ACCENT_PURPLE": "#00cc66", "ACCENT_PINK": "#88ff00",
        "TEXT": "#c0f0c0", "TEXT_DIM": "#4a8a4a", "TEXT_BRIGHT": "#e0ffe0",
        "BAND_LOW": "#00cc66", "BAND_MID": "#00ff88", "BAND_HIGH": "#88ff00",
        "METER_LOW": "#00cc66", "METER_MID": "#00ff88", "METER_HIGH": "#ffff00",
        "PEAK_LED": "#ff8800", "CLIP_LED": "#ff2200",
        "HEATMAP_STOPS": [
            (0.00, "#000000"), (0.30, "#004422"), (0.60, "#00aa55"),
            (0.85, "#44ff88"), (1.00, "#aaffcc")
        ]
    },
    "Ember": {
        "BG_DARKEST": "#0c0806", "BG_DARK": "#140e0a", "BG_MODULE": "#1a1410",
        "BG_HEADER": "#221a14", "BG_SETTINGS": "#2a2018", "BG_INPUT": "#120e08",
        "BG_BADGE": "#2a1800", "BG_BADGE_ALPHA": 180,
        "BORDER": "#3a2a1a", "BORDER_ACCENT": "#5a4030",
        "ACCENT": "#ff8800", "ACCENT_DIM": "#aa5500",
        "ACCENT_PURPLE": "#ff6622", "ACCENT_PINK": "#ffaa44",
        "TEXT": "#f0dcc0", "TEXT_DIM": "#8a6a4a", "TEXT_BRIGHT": "#fff0dd",
        "BAND_LOW": "#ff8800", "BAND_MID": "#ff6622", "BAND_HIGH": "#ffaa44",
        "METER_LOW": "#aa5500", "METER_MID": "#ff8800", "METER_HIGH": "#ffaa44",
        "PEAK_LED": "#ffdd00", "CLIP_LED": "#ff2200",
        "HEATMAP_STOPS": [
            (0.00, "#000000"), (0.30, "#441100"), (0.60, "#aa4400"),
            (0.85, "#ff8800"), (1.00, "#ffcc88")
        ]
    },
    "Amethyst": {
        "BG_DARKEST": "#08060f", "BG_DARK": "#100c1a", "BG_MODULE": "#161222",
        "BG_HEADER": "#1e1830", "BG_SETTINGS": "#241e38", "BG_INPUT": "#0e0a18",
        "BG_BADGE": "#1e1435", "BG_BADGE_ALPHA": 180,
        "BORDER": "#302848", "BORDER_ACCENT": "#4a3a6a",
        "ACCENT": "#b060ff", "ACCENT_DIM": "#7030aa",
        "ACCENT_PURPLE": "#9040dd", "ACCENT_PINK": "#d080ff",
        "TEXT": "#dcd0f0", "TEXT_DIM": "#7868a0", "TEXT_BRIGHT": "#f0e8ff",
        "BAND_LOW": "#7c4dff", "BAND_MID": "#b060ff", "BAND_HIGH": "#d080ff",
        "METER_LOW": "#7030aa", "METER_MID": "#b060ff", "METER_HIGH": "#ff44cc",
        "PEAK_LED": "#ffaa00", "CLIP_LED": "#ff2244",
        "HEATMAP_STOPS": [
            (0.00, "#000000"), (0.30, "#220044"), (0.60, "#6600aa"),
            (0.85, "#aa44ff"), (1.00, "#eebbaa")
        ]
    },
    "Transparent Ghost": {
        "BG_DARKEST": "#05000000", "BG_DARK": "#05000000", "BG_MODULE": "#05000000",
        "BG_HEADER": "#05000000", "BG_SETTINGS": "#05000000", "BG_INPUT": "#05000000",
        "BG_BADGE": "#0a0a2a", "BG_BADGE_ALPHA": 120,
        "BORDER": "#00000000", "BORDER_ACCENT": "#00000000",
        "ACCENT": "#00d4ff", "ACCENT_DIM": "#0088aa",
        "ACCENT_PURPLE": "#7c4dff", "ACCENT_PINK": "#ff4da6",
        "TEXT": "#d8d8f0", "TEXT_DIM": "#7878a0", "TEXT_BRIGHT": "#f0f0ff",
        "BAND_LOW": "#0088ff", "BAND_MID": "#00e87b", "BAND_HIGH": "#ff4444",
        "METER_LOW": "#0088ff", "METER_MID": "#00e87b", "METER_HIGH": "#ff4444",
        "PEAK_LED": "#ffcc00", "CLIP_LED": "#ff2244",
        "HEATMAP_STOPS": [
            (0.00, "#05000000"), (0.15, "#0a0040"), (0.30, "#0044cc"),
            (0.45, "#00bbcc"), (0.55, "#00cc44"), (0.70, "#cccc00"),
            (0.85, "#cc4400"), (1.00, "#ff0000")
        ]
    },
    "Slate": {
        "BG_DARKEST": "#1a1b26", "BG_DARK": "#24283b", "BG_MODULE": "#2f354a",
        "BG_HEADER": "#3b4261", "BG_SETTINGS": "#414868", "BG_INPUT": "#1a1b26",
        "BG_BADGE": "#2f354a", "BG_BADGE_ALPHA": 180,
        "BORDER": "#565f89", "BORDER_ACCENT": "#7aa2f7",
        "ACCENT": "#7aa2f7", "ACCENT_DIM": "#2ac3de",
        "ACCENT_PURPLE": "#bb9af7", "ACCENT_PINK": "#f7768e",
        "TEXT": "#c0caf5", "TEXT_DIM": "#a9b1d6", "TEXT_BRIGHT": "#ffffff",
        "BAND_LOW": "#7aa2f7", "BAND_MID": "#9ece6a", "BAND_HIGH": "#f7768e",
        "METER_LOW": "#2ac3de", "METER_MID": "#9ece6a", "METER_HIGH": "#f7768e",
        "PEAK_LED": "#ffcc00", "CLIP_LED": "#ff2244",
    },
    "Modern Light": {
        "BG_DARKEST": "#f0f0f5", "BG_DARK": "#ffffff", "BG_MODULE": "#fcfcfd",
        "BG_HEADER": "#e8e8f0", "BG_SETTINGS": "#ffffff", "BG_INPUT": "#f5f5f9",
        "BG_BADGE": "#dde8f8", "BG_BADGE_ALPHA": 180,
        "BORDER": "#d1d1e0", "BORDER_ACCENT": "#4a90e2",
        "ACCENT": "#4a90e2", "ACCENT_DIM": "#357abd",
        "ACCENT_PURPLE": "#9013fe", "ACCENT_PINK": "#d0021b",
        "TEXT": "#2c3e50", "TEXT_DIM": "#7f8c8d", "TEXT_BRIGHT": "#000000",
        "BAND_LOW": "#4a90e2", "BAND_MID": "#40c057", "BAND_HIGH": "#fa5252",
        "METER_LOW": "#4a90e2", "METER_MID": "#357abd", "METER_HIGH": "#d0021b",
        "PEAK_LED": "#ff8800", "CLIP_LED": "#ff2244",
        "HEATMAP_STOPS": [
            (0.00, "#ffffff"), (0.30, "#e8f4fd"), (0.60, "#a0d1f7"),
            (0.85, "#4a90e2"), (1.00, "#2c3e50")
        ]
    },
    "Glass": {
        "BG_DARKEST": "#10ffffff", "BG_DARK": "#15ffffff", "BG_MODULE": "#20ffffff",
        "BG_HEADER": "#30ffffff", "BG_SETTINGS": "#40ffffff", "BG_INPUT": "#10ffffff",
        "BG_BADGE": "#ffffff", "BG_BADGE_ALPHA": 40,
        "BORDER": "#40ffffff", "BORDER_ACCENT": "#80ffffff",
        "ACCENT": "#ffffff", "ACCENT_DIM": "#cccccc",
        "ACCENT_PURPLE": "#e0e0e0", "ACCENT_PINK": "#f0f0f0",
        "TEXT": "#ffffff", "TEXT_DIM": "#dddddd", "TEXT_BRIGHT": "#ffffff",
        "BAND_LOW": "#ffffff", "BAND_MID": "#eeeeee", "BAND_HIGH": "#dddddd",
        "METER_LOW": "#cccccc", "METER_MID": "#eeeeee", "METER_HIGH": "#ffffff",
        "PEAK_LED": "#ffdd88", "CLIP_LED": "#ff8899",
    },
    "Aurora": {
        "BG_DARKEST": "#05101a", "BG_DARK": "#0a1f30", "BG_MODULE": "#0f2a42",
        "BG_HEADER": "#163550", "BG_SETTINGS": "#1a3d5c", "BG_INPUT": "#081828",
        "BG_BADGE": "#071e28", "BG_BADGE_ALPHA": 180,
        "BORDER": "#1a4060", "BORDER_ACCENT": "#2a6080",
        "ACCENT": "#00ffcc", "ACCENT_DIM": "#00aa88",
        "ACCENT_PURPLE": "#00ccff", "ACCENT_PINK": "#ff44aa",
        "TEXT": "#c0f5e8", "TEXT_DIM": "#4a8a78", "TEXT_BRIGHT": "#e0fff8",
        "BAND_LOW": "#00ccff", "BAND_MID": "#00ffcc", "BAND_HIGH": "#ff44aa",
        "METER_LOW": "#00ccff", "METER_MID": "#00ffcc", "METER_HIGH": "#ff44aa",
        "PEAK_LED": "#ffcc00", "CLIP_LED": "#ff2244",
        "HEATMAP_STOPS": [
            (0.00, "#000000"), (0.30, "#001a22"), (0.60, "#00667a"),
            (0.85, "#00ffcc"), (1.00, "#aaffee")
        ]
    },
    "Crimson": {
        "BG_DARKEST": "#100508", "BG_DARK": "#1a080c", "BG_MODULE": "#220a10",
        "BG_HEADER": "#2a0c14", "BG_SETTINGS": "#321018", "BG_INPUT": "#150608",
        "BG_BADGE": "#2a0810", "BG_BADGE_ALPHA": 180,
        "BORDER": "#3a1020", "BORDER_ACCENT": "#5a1830",
        "ACCENT": "#ff2255", "ACCENT_DIM": "#aa1133",
        "ACCENT_PURPLE": "#ff0044", "ACCENT_PINK": "#ff6688",
        "TEXT": "#f0c0cc", "TEXT_DIM": "#8a4050", "TEXT_BRIGHT": "#ffe0e8",
        "BAND_LOW": "#ff2255", "BAND_MID": "#ff0044", "BAND_HIGH": "#ff6688",
        "METER_LOW": "#cc2244", "METER_MID": "#ff2255", "METER_HIGH": "#ff6688",
        "PEAK_LED": "#ffaa00", "CLIP_LED": "#ffffff",
        "HEATMAP_STOPS": [
            (0.00, "#000000"), (0.30, "#440011"), (0.60, "#aa0033"),
            (0.85, "#ff2255"), (1.00, "#ffaabb")
        ]
    },
    "Solar": {
        "BG_DARKEST": "#0f0c00", "BG_DARK": "#1a1400", "BG_MODULE": "#241c00",
        "BG_HEADER": "#2e2400", "BG_SETTINGS": "#382c00", "BG_INPUT": "#120e00",
        "BG_BADGE": "#2a1e00", "BG_BADGE_ALPHA": 180,
        "BORDER": "#3a3000", "BORDER_ACCENT": "#5a4c00",
        "ACCENT": "#ffd700", "ACCENT_DIM": "#aa9000",
        "ACCENT_PURPLE": "#ffaa00", "ACCENT_PINK": "#ffe066",
        "TEXT": "#fff0b0", "TEXT_DIM": "#8a7a30", "TEXT_BRIGHT": "#fffde0",
        "BAND_LOW": "#ffaa00", "BAND_MID": "#ffd700", "BAND_HIGH": "#ffe066",
        "METER_LOW": "#ffaa00", "METER_MID": "#ffd700", "METER_HIGH": "#ffffff",
        "PEAK_LED": "#ff6600", "CLIP_LED": "#ff2200",
        "HEATMAP_STOPS": [
            (0.00, "#000000"), (0.30, "#1a1000"), (0.60, "#665500"),
            (0.85, "#ffd700"), (1.00, "#fffacc")
        ]
    },
    "Arctic": {
        "BG_DARKEST": "#060e18", "BG_DARK": "#0c1828", "BG_MODULE": "#122035",
        "BG_HEADER": "#182840", "BG_SETTINGS": "#1e304c", "BG_INPUT": "#090e18",
        "BG_BADGE": "#0a1828", "BG_BADGE_ALPHA": 180,
        "BORDER": "#1e3a55", "BORDER_ACCENT": "#2e5070",
        "ACCENT": "#88ddff", "ACCENT_DIM": "#3399cc",
        "ACCENT_PURPLE": "#aaddff", "ACCENT_PINK": "#66aadd",
        "TEXT": "#d0eeff", "TEXT_DIM": "#5080a0", "TEXT_BRIGHT": "#f0faff",
        "BAND_LOW": "#6699cc", "BAND_MID": "#88ddff", "BAND_HIGH": "#aaddff",
        "METER_LOW": "#3399cc", "METER_MID": "#88ddff", "METER_HIGH": "#ff4466",
        "PEAK_LED": "#ffcc44", "CLIP_LED": "#ff3322",
        "HEATMAP_STOPS": [
            (0.00, "#000000"), (0.30, "#031422"), (0.60, "#105080"),
            (0.85, "#88ddff"), (1.00, "#ddf4ff")
        ]
    },
    "Absinthe": {
        "BG_DARKEST": "#060f08", "BG_DARK": "#0c1a10", "BG_MODULE": "#122018",
        "BG_HEADER": "#182a20", "BG_SETTINGS": "#1e3228", "BG_INPUT": "#090e0a",
        "BG_BADGE": "#0e2214", "BG_BADGE_ALPHA": 180,
        "BORDER": "#203820", "BORDER_ACCENT": "#304e30",
        "ACCENT": "#88ff44", "ACCENT_DIM": "#55aa22",
        "ACCENT_PURPLE": "#66dd33", "ACCENT_PINK": "#ccff88",
        "TEXT": "#d0f0b8", "TEXT_DIM": "#507840", "TEXT_BRIGHT": "#eeffcc",
        "BAND_LOW": "#66dd33", "BAND_MID": "#88ff44", "BAND_HIGH": "#ccff88",
        "METER_LOW": "#55aa22", "METER_MID": "#88ff44", "METER_HIGH": "#ffff00",
        "PEAK_LED": "#ff8800", "CLIP_LED": "#ff2200",
        "HEATMAP_STOPS": [
            (0.00, "#000000"), (0.30, "#091a04"), (0.60, "#2a6010"),
            (0.85, "#88ff44"), (1.00, "#d4ffaa")
        ]
    },
    "Rose Quartz": {
        "BG_DARKEST": "#0f080c", "BG_DARK": "#1a1018", "BG_MODULE": "#221520",
        "BG_HEADER": "#2a1a28", "BG_SETTINGS": "#321e30", "BG_INPUT": "#120a10",
        "BG_BADGE": "#2a1020", "BG_BADGE_ALPHA": 180,
        "BORDER": "#3a2030", "BORDER_ACCENT": "#5a3050",
        "ACCENT": "#ff80b0", "ACCENT_DIM": "#cc4488",
        "ACCENT_PURPLE": "#dd60a0", "ACCENT_PINK": "#ffaacf",
        "TEXT": "#f0d0dc", "TEXT_DIM": "#8a5068", "TEXT_BRIGHT": "#ffecf2",
        "BAND_LOW": "#dd60a0", "BAND_MID": "#ff80b0", "BAND_HIGH": "#ffaacf",
        "METER_LOW": "#cc4488", "METER_MID": "#ff80b0", "METER_HIGH": "#ffaacf",
        "PEAK_LED": "#ffaa00", "CLIP_LED": "#ff2244",
        "HEATMAP_STOPS": [
            (0.00, "#000000"), (0.30, "#330018"), (0.60, "#991055"),
            (0.85, "#ff80b0"), (1.00, "#ffcce0")
        ]
    },
    "Transparent Crimson": {
        "BG_DARKEST": "#05000000", "BG_DARK": "#05000000", "BG_MODULE": "#05000000",
        "BG_HEADER": "#05000000", "BG_SETTINGS": "#05000000", "BG_INPUT": "#05000000",
        "BG_BADGE": "#220008", "BG_BADGE_ALPHA": 120,
        "BORDER": "#00000000", "BORDER_ACCENT": "#00000000",
        "ACCENT": "#ff2255", "ACCENT_DIM": "#aa1133",
        "ACCENT_PURPLE": "#ff0044", "ACCENT_PINK": "#ff6688",
        "TEXT": "#f0c0cc", "TEXT_DIM": "#8a4050", "TEXT_BRIGHT": "#ffe0e8",
        "BAND_LOW": "#ff2255", "BAND_MID": "#ff0044", "BAND_HIGH": "#ff6688",
        "METER_LOW": "#cc2244", "METER_MID": "#ff2255", "METER_HIGH": "#ff6688",
        "PEAK_LED": "#ffaa00", "CLIP_LED": "#ffffff",
        "HEATMAP_STOPS": [
            (0.00, "#05000000"), (0.15, "#4a001122"), (0.30, "#aa003355"),
            (0.55, "#ff2255bb"), (1.00, "#ff6688ff")
        ]
    },
    "Transparent Aurora": {
        "BG_DARKEST": "#05000000", "BG_DARK": "#05000000", "BG_MODULE": "#05000000",
        "BG_HEADER": "#05000000", "BG_SETTINGS": "#05000000", "BG_INPUT": "#05000000",
        "BG_BADGE": "#041418", "BG_BADGE_ALPHA": 120,
        "BORDER": "#00000000", "BORDER_ACCENT": "#00000000",
        "ACCENT": "#00ffcc", "ACCENT_DIM": "#00aa88",
        "ACCENT_PURPLE": "#00ccff", "ACCENT_PINK": "#ff44aa",
        "TEXT": "#c0f5e8", "TEXT_DIM": "#4a8a78", "TEXT_BRIGHT": "#e0fff8",
        "BAND_LOW": "#00ccff", "BAND_MID": "#00ffcc", "BAND_HIGH": "#ff44aa",
        "METER_LOW": "#00ccff", "METER_MID": "#00ffcc", "METER_HIGH": "#ff44aa",
        "PEAK_LED": "#ffcc00", "CLIP_LED": "#ff2244",
        "HEATMAP_STOPS": [
            (0.00, "#05000000"), (0.15, "#0a2a3a44"), (0.30, "#00667a88"),
            (0.55, "#00ffcccc"), (1.00, "#aaffeeff")
        ]
    },
    "Verdant": {
        "BG_DARKEST": "#060e06", "BG_DARK": "#0a140a", "BG_MODULE": "#111b11",
        "BG_HEADER": "#162116", "BG_SETTINGS": "#1a281a", "BG_INPUT": "#090e09",
        "BG_BADGE": "#0a1e0e", "BG_BADGE_ALPHA": 180,
        "BORDER": "#1a3a1a", "BORDER_ACCENT": "#1ed760",
        "ACCENT": "#1ed760", "ACCENT_DIM": "#158a3e",
        "ACCENT_PURPLE": "#1db954", "ACCENT_PINK": "#1fdf64",
        "TEXT": "#ffffff", "TEXT_DIM": "#a0a0a0", "TEXT_BRIGHT": "#ffffff",
        "BAND_LOW": "#1db954", "BAND_MID": "#1ed760", "BAND_HIGH": "#1fdf64",
        "METER_LOW": "#1db954", "METER_MID": "#1ed760", "METER_HIGH": "#ffff00",
        "PEAK_LED": "#ff8800", "CLIP_LED": "#ff2200",
        "HEATMAP_STOPS": [
            (0.00, "#060e06"), (0.30, "#0a2a14"), (0.60, "#0f6630"),
            (0.85, "#1ed760"), (1.00, "#aaffcc")
        ]
    },
    "Tangerine": {
        "BG_DARKEST": "#0f0a00", "BG_DARK": "#1a1000", "BG_MODULE": "#221600",
        "BG_HEADER": "#2a1c00", "BG_SETTINGS": "#332200", "BG_INPUT": "#160e00",
        "BG_BADGE": "#221200", "BG_BADGE_ALPHA": 180,
        "BORDER": "#3d2600", "BORDER_ACCENT": "#ff8c00",
        "ACCENT": "#ff8c00", "ACCENT_DIM": "#cc6600",
        "ACCENT_PURPLE": "#ff6600", "ACCENT_PINK": "#ffaa33",
        "TEXT": "#fff0d0", "TEXT_DIM": "#997744", "TEXT_BRIGHT": "#ffffff",
        "BAND_LOW": "#ff6600", "BAND_MID": "#ff8c00", "BAND_HIGH": "#ffaa33",
        "METER_LOW": "#cc6600", "METER_MID": "#ff8c00", "METER_HIGH": "#ffdd00",
        "PEAK_LED": "#ffffff", "CLIP_LED": "#ff2200",
        "HEATMAP_STOPS": [
            (0.00, "#0f0a00"), (0.30, "#3a1a00"), (0.60, "#aa4400"),
            (0.85, "#ff8c00"), (1.00, "#ffeeaa")
        ]
    },
    "Obsidian Wave": {
        "BG_DARKEST": "#000000", "BG_DARK": "#080808", "BG_MODULE": "#101010",
        "BG_HEADER": "#181818", "BG_SETTINGS": "#202020", "BG_INPUT": "#080808",
        "BG_BADGE": "#111111", "BG_BADGE_ALPHA": 180,
        "BORDER": "#2a2a2a", "BORDER_ACCENT": "#ffffff",
        "ACCENT": "#ffffff", "ACCENT_DIM": "#aaaaaa",
        "ACCENT_PURPLE": "#cccccc", "ACCENT_PINK": "#e0e0e0",
        "TEXT": "#ffffff", "TEXT_DIM": "#888888", "TEXT_BRIGHT": "#ffffff",
        "BAND_LOW": "#aaaaaa", "BAND_MID": "#cccccc", "BAND_HIGH": "#ffffff",
        "METER_LOW": "#888888", "METER_MID": "#cccccc", "METER_HIGH": "#ffffff",
        "PEAK_LED": "#dddddd", "CLIP_LED": "#ffffff",
        "HEATMAP_STOPS": [
            (0.00, "#000000"), (0.30, "#1a1a1a"), (0.60, "#555555"),
            (0.85, "#bbbbbb"), (1.00, "#ffffff")
        ]
    },
    "Ivory": {
        "BG_DARKEST": "#0a0a0a", "BG_DARK": "#141414", "BG_MODULE": "#1c1c1c",
        "BG_HEADER": "#242424", "BG_SETTINGS": "#2a2a2a", "BG_INPUT": "#111111",
        "BG_BADGE": "#1a0a0c", "BG_BADGE_ALPHA": 180,
        "BORDER": "#383838", "BORDER_ACCENT": "#fc3c44",
        "ACCENT": "#fc3c44", "ACCENT_DIM": "#c0222a",
        "ACCENT_PURPLE": "#dd2233", "ACCENT_PINK": "#ff6066",
        "TEXT": "#f5f5f7", "TEXT_DIM": "#888888", "TEXT_BRIGHT": "#ffffff",
        "BAND_LOW": "#dd2233", "BAND_MID": "#fc3c44", "BAND_HIGH": "#ff6066",
        "METER_LOW": "#c0222a", "METER_MID": "#fc3c44", "METER_HIGH": "#ff6066",
        "PEAK_LED": "#ff8800", "CLIP_LED": "#ff2244",
        "HEATMAP_STOPS": [
            (0.00, "#0a0a0a"), (0.30, "#2a0a0c"), (0.60, "#880010"),
            (0.85, "#fc3c44"), (1.00, "#ffaaaa")
        ]
    },
    "Blueprint": {
        "BG_DARKEST": "#0f0f0f", "BG_DARK": "#1a1a1a", "BG_MODULE": "#222222",
        "BG_HEADER": "#2a2a2a", "BG_SETTINGS": "#313131", "BG_INPUT": "#161616",
        "BG_BADGE": "#141a24", "BG_BADGE_ALPHA": 180,
        "BORDER": "#3a3a3a", "BORDER_ACCENT": "#4a90d9",
        "ACCENT": "#4a90d9", "ACCENT_DIM": "#2a6099",
        "ACCENT_PURPLE": "#3a7acc", "ACCENT_PINK": "#66aaee",
        "TEXT": "#e0e0e0", "TEXT_DIM": "#777777", "TEXT_BRIGHT": "#ffffff",
        "BAND_LOW": "#3a7acc", "BAND_MID": "#4a90d9", "BAND_HIGH": "#66aaee",
        "METER_LOW": "#2a6099", "METER_MID": "#4a90d9", "METER_HIGH": "#aaddff",
        "PEAK_LED": "#ffcc00", "CLIP_LED": "#ff2244",
        "HEATMAP_STOPS": [
            (0.00, "#0f0f0f"), (0.30, "#0a1a2a"), (0.60, "#0a4488"),
            (0.85, "#4a90d9"), (1.00, "#aaddff")
        ]
    },
    "Ultraviolet": {
        "BG_DARKEST": "#080808", "BG_DARK": "#111111", "BG_MODULE": "#181818",
        "BG_HEADER": "#202020", "BG_SETTINGS": "#262626", "BG_INPUT": "#0e0e0e",
        "BG_BADGE": "#1a0e08", "BG_BADGE_ALPHA": 180,
        "BORDER": "#2e2e2e", "BORDER_ACCENT": "#ff5500",
        "ACCENT": "#ff5500", "ACCENT_DIM": "#cc3300",
        "ACCENT_PURPLE": "#ff4400", "ACCENT_PINK": "#ff7733",
        "TEXT": "#f0f0f0", "TEXT_DIM": "#888888", "TEXT_BRIGHT": "#ffffff",
        "BAND_LOW": "#ff4400", "BAND_MID": "#ff5500", "BAND_HIGH": "#ff7733",
        "METER_LOW": "#cc3300", "METER_MID": "#ff5500", "METER_HIGH": "#ffaa00",
        "PEAK_LED": "#ffdd00", "CLIP_LED": "#ff2200",
        "HEATMAP_STOPS": [
            (0.00, "#080808"), (0.30, "#2a0e00"), (0.60, "#aa2200"),
            (0.85, "#ff5500"), (1.00, "#ffcc88")
        ]
    },
    "Cobalt": {
        "BG_DARKEST": "#05080f", "BG_DARK": "#0a1020", "BG_MODULE": "#10182e",
        "BG_HEADER": "#162038", "BG_SETTINGS": "#1c2844", "BG_INPUT": "#080e1a",
        "BG_BADGE": "#081020", "BG_BADGE_ALPHA": 180,
        "BORDER": "#1e2e4a", "BORDER_ACCENT": "#2c6be0",
        "ACCENT": "#2c6be0", "ACCENT_DIM": "#1a44aa",
        "ACCENT_PURPLE": "#2255cc", "ACCENT_PINK": "#4488ff",
        "TEXT": "#c8d8f8", "TEXT_DIM": "#5570a0", "TEXT_BRIGHT": "#ffffff",
        "BAND_LOW": "#2255cc", "BAND_MID": "#2c6be0", "BAND_HIGH": "#4488ff",
        "METER_LOW": "#1a44aa", "METER_MID": "#2c6be0", "METER_HIGH": "#88bbff",
        "PEAK_LED": "#ffcc00", "CLIP_LED": "#ff2244",
        "HEATMAP_STOPS": [
            (0.00, "#05080f"), (0.30, "#081030"), (0.60, "#0a3088"),
            (0.85, "#2c6be0"), (1.00, "#aaccff")
        ]
    },
    "Highlighter": {
        "BG_DARKEST": "#f5f5e0", "BG_DARK": "#fafaf0", "BG_MODULE": "#fffff5",
        "BG_HEADER": "#eeeecc", "BG_SETTINGS": "#fafae8", "BG_INPUT": "#f8f8e8",
        "BG_BADGE": "#e8eebb", "BG_BADGE_ALPHA": 180,
        "BORDER": "#cccc44", "BORDER_ACCENT": "#aacc00",
        "ACCENT": "#88cc00", "ACCENT_DIM": "#558800",
        "ACCENT_PURPLE": "#aacc00", "ACCENT_PINK": "#ccdd00",
        "TEXT": "#222200", "TEXT_DIM": "#667722", "TEXT_BRIGHT": "#000000",
        "BAND_LOW": "#88cc00", "BAND_MID": "#aacc00", "BAND_HIGH": "#ccdd00",
        "METER_LOW": "#88cc00", "METER_MID": "#aacc00", "METER_HIGH": "#dd4400",
        "PEAK_LED": "#ff6600", "CLIP_LED": "#ff0000",
        "HEATMAP_STOPS": [
            (0.00, "#fffff5"), (0.30, "#eeffaa"), (0.60, "#ccee44"),
            (0.85, "#88cc00"), (1.00, "#446600")
        ]
    },
    "Bubblegum": {
        "BG_DARKEST": "#f5e8f0", "BG_DARK": "#fdf0f8", "BG_MODULE": "#fff5fc",
        "BG_HEADER": "#f0daea", "BG_SETTINGS": "#fdf0f8", "BG_INPUT": "#fae8f5",
        "BG_BADGE": "#f0ccdd", "BG_BADGE_ALPHA": 180,
        "BORDER": "#ddaacc", "BORDER_ACCENT": "#ff44aa",
        "ACCENT": "#ff44aa", "ACCENT_DIM": "#cc1177",
        "ACCENT_PURPLE": "#ee22aa", "ACCENT_PINK": "#ff77cc",
        "TEXT": "#220011", "TEXT_DIM": "#994477", "TEXT_BRIGHT": "#000000",
        "BAND_LOW": "#ee22aa", "BAND_MID": "#ff44aa", "BAND_HIGH": "#ff77cc",
        "METER_LOW": "#cc1177", "METER_MID": "#ff44aa", "METER_HIGH": "#ff77cc",
        "PEAK_LED": "#ff8800", "CLIP_LED": "#ff2244",
        "HEATMAP_STOPS": [
            (0.00, "#fff5fc"), (0.30, "#ffccee"), (0.60, "#ff88cc"),
            (0.85, "#ff44aa"), (1.00, "#880044")
        ]
    }
}


THEME_GROUPS = {
    "Dark": ["Midnight", "Abyss", "Slate", "Obsidian Wave", "Ivory", "Blueprint"],
    "Vibrant": ["Neon", "Ember", "Amethyst", "Crimson", "Solar",
                "Aurora", "Absinthe", "Rose Quartz", "Verdant", "Tangerine", "Ultraviolet"],
    "Cool": ["Arctic", "Cobalt"],
    "Light": ["Modern Light", "Highlighter", "Bubblegum"],
    "Transparent": ["Transparent Ghost", "Glass",
                    "Transparent Crimson", "Transparent Aurora"],
}

INVALID_THEMES = {}
CUSTOM_THEME_LOAD_ERROR = None


_HEX_COLOR_RE = re.compile(r"^#(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{4}|[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$")
_EXTRA_THEME_KEYS = {
    "GREEN", "YELLOW", "RED", "GRID", "GRID_BRIGHT",
    "VU_CREAM", "VU_DARK_FACE", "VU_NEEDLE", "VU_RED_ZONE",
}
_KNOWN_THEME_KEYS = set(_EXTRA_THEME_KEYS)
for _preset in THEME_PRESETS.values():
    _KNOWN_THEME_KEYS.update(_preset.keys())


def _valid_hex_color(value):
    return isinstance(value, str) and bool(_HEX_COLOR_RE.match(value))


def _validate_heatmap_stops(value):
    if not isinstance(value, list) or not value:
        return "must be a non-empty list of [position, color] pairs"

    last_pos = -1.0
    for index, stop in enumerate(value):
        if not isinstance(stop, (list, tuple)) or len(stop) != 2:
            return f"stop {index + 1} must be [position, color]"
        pos, color = stop
        if not isinstance(pos, (int, float)) or not 0.0 <= float(pos) <= 1.0:
            return f"stop {index + 1} position must be a number from 0.0 to 1.0"
        if float(pos) < last_pos:
            return f"stop {index + 1} position must not go backwards"
        if not _valid_hex_color(color):
            return f"stop {index + 1} color must be a hex color like #00d4ff"
        last_pos = float(pos)
    return None

def load_custom_themes():
    import json
    import os
    import logging
    from app.settings import SettingsManager

    global CUSTOM_THEME_LOAD_ERROR
    CUSTOM_THEME_LOAD_ERROR = None
    INVALID_THEMES.clear()
    if "Custom" in THEME_GROUPS:
        THEME_GROUPS["Custom"].clear()

    path = os.path.join(SettingsManager.get_app_data_dir(), "themes.json")
    template = {
        "My Custom Theme": {
            "__comment": "Remove this comment and fill in valid hex codes to use this theme.",
            "BG_DARKEST": "#000000",
            "ACCENT": "#ffffff"
        }
    }
    
    if not os.path.exists(path):
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(template, f, indent=4)
        except Exception as e:
            CUSTOM_THEME_LOAD_ERROR = f"Could not create themes.json: {e}"
            logging.error(CUSTOM_THEME_LOAD_ERROR)
        return

    try:
        with open(path, "r", encoding="utf-8") as f:
            custom_themes = json.load(f)
    except json.JSONDecodeError as e:
        CUSTOM_THEME_LOAD_ERROR = f"themes.json has malformed JSON at line {e.lineno}, column {e.colno}: {e.msg}"
        logging.error(CUSTOM_THEME_LOAD_ERROR)
        return
    except Exception as e:
        CUSTOM_THEME_LOAD_ERROR = f"Could not read themes.json: {e}"
        logging.error(CUSTOM_THEME_LOAD_ERROR)
        return
        
    if not isinstance(custom_themes, dict):
        CUSTOM_THEME_LOAD_ERROR = "themes.json must contain a JSON object of theme names."
        logging.error(CUSTOM_THEME_LOAD_ERROR)
        return
        
    THEME_GROUPS["Custom"] = []
        
    for name, theme_data in custom_themes.items():
        if not isinstance(name, str) or not name.strip():
            INVALID_THEMES[str(name)] = "Theme names must be non-empty strings."
            THEME_GROUPS["Custom"].append(f"{name} [!]")
            continue

        if name == "My Custom Theme" and "__comment" in theme_data:
            continue
            
        if not isinstance(theme_data, dict):
            INVALID_THEMES[name] = "Theme data must be a dictionary of color values."
            THEME_GROUPS["Custom"].append(f"{name} [!]")
            continue
            
        errors = []
        for k, v in theme_data.items():
            if k == "__comment": continue
            if k not in _KNOWN_THEME_KEYS:
                errors.append(f"{k}: unknown color key")
                continue
            
            if k == "HEATMAP_STOPS":
                error = _validate_heatmap_stops(v)
                if error:
                    errors.append(f"{k}: {error}")
                continue
                
            if k.endswith("_ALPHA"):
                if not isinstance(v, (int, float)) or not 0 <= v <= 255:
                    errors.append(f"{k}: must be a number from 0 to 255")
                continue

            if not _valid_hex_color(v):
                errors.append(f"{k}: must be a hex color like #00d4ff")
                
        if errors:
            INVALID_THEMES[name] = "; ".join(errors)
            THEME_GROUPS["Custom"].append(f"{name} [!]")
        else:
            THEME_PRESETS[name] = theme_data
            THEME_GROUPS["Custom"].append(name)
            
    # Clean up empty Custom group
    if not THEME_GROUPS["Custom"]:
        del THEME_GROUPS["Custom"]

load_custom_themes()


class Colors:
    """Active color palette. Values are updated by apply_theme()."""
    BG_DARKEST = "#08080f"
    BG_DARK = "#0e0e1a"
    BG_MODULE = "#131320"
    BG_HEADER = "#181830"
    BG_SETTINGS = "#1a1a2e"
    BG_INPUT = "#10101e"
    BG_BADGE = "#000000" # Background for labels/badges
    BG_BADGE_ALPHA = 180 # Default transparency for badges
    BORDER = "#252545"
    BORDER_ACCENT = "#3a3a6a"

    ACCENT = "#00d4ff"
    ACCENT_DIM = "#0088aa"
    ACCENT_PURPLE = "#7c4dff"
    ACCENT_PINK = "#ff4da6"

    TEXT = "#d8d8f0"
    TEXT_DIM = "#7878a0"
    TEXT_BRIGHT = "#f0f0ff"

    # Meter colors (overridable by themes)
    METER_LOW = "#00e87b"
    METER_MID = "#f0c800"
    METER_HIGH = "#ff2244"
    PEAK_LED = "#ff2244"
    CLIP_LED = "#ff2244"
    
    # Internal aliases for backward compatibility
    GREEN = "#00e87b"
    YELLOW = "#f0c800"
    RED = "#ff2244"

    # Multi-band
    BAND_LOW = "#0088ff"
    BAND_MID = "#00e87b"
    BAND_HIGH = "#ff4444"

    HEATMAP_STOPS = [
        (0.00, "#000000"), (0.15, "#0a0040"), (0.30, "#0044cc"),
        (0.45, "#00bbcc"), (0.55, "#00cc44"), (0.70, "#cccc00"),
        (0.85, "#cc4400"), (1.00, "#ff0000")
    ]

    # Grid / subtle
    GRID = "#1a1a32"
    GRID_BRIGHT = "#252548"

    # VU meter
    VU_CREAM = "#f5f0e0"
    VU_DARK_FACE = "#1a1a28"
    VU_NEEDLE = "#cc2200"
    VU_RED_ZONE = "#ff3333"

    @staticmethod
    def q(hex_color: str) -> QColor:
        return QColor(hex_color)

    @staticmethod
    def with_alpha(hex_color: str, alpha: int) -> QColor:
        c = QColor(hex_color)
        c.setAlpha(alpha)
        return c


_current_theme = "Midnight"


def apply_theme(name: str, overrides: dict = None):
    """Switch the active color palette to the named preset and apply optional overrides."""
    global _current_theme
    if name not in THEME_PRESETS:
        return
    _current_theme = name
    
    # Baseline defaults (Midnight) to ensure we don't leak specialized colors from previous themes
    defaults = THEME_PRESETS["Midnight"]
    # Keys that are often missing in simpler themes but should reset
    reset_keys = ["BAND_LOW", "BAND_MID", "BAND_HIGH", "HEATMAP_STOPS", "METER_LOW", "METER_MID", "METER_HIGH", "PEAK_LED", "CLIP_LED", "BORDER", "BORDER_ACCENT", "BG_BADGE", "BG_BADGE_ALPHA"]
    
    # 1. Reset baseline for specific keys from Defaults
    for key in reset_keys:
        if key in defaults:
            setattr(Colors, key, defaults[key])

    # Sync back-compat aliases
    Colors.GREEN = Colors.METER_LOW
    Colors.YELLOW = Colors.METER_MID
    Colors.RED = Colors.METER_HIGH
            
    # 2. Apply the chosen preset
    preset = THEME_PRESETS[name]
    for attr, value in preset.items():
        if hasattr(Colors, attr):
            setattr(Colors, attr, value)
    
    # Sync back-compat aliases after preset
    Colors.GREEN = Colors.METER_LOW
    Colors.YELLOW = Colors.METER_MID
    Colors.RED = Colors.METER_HIGH

    # 3. Apply optional overrides
    if overrides:
        for attr, value in overrides.items():
            if hasattr(Colors, attr):
                setattr(Colors, attr, value)


def current_theme_name() -> str:
    return _current_theme


# (Use Colors.HEATMAP_STOPS instead)


class Fonts:
    FAMILY = "Segoe UI"
    FAMILY_MONO = "Cascadia Code"
    TEXT_SCALE = 1.0

    @staticmethod
    def header() -> QFont:
        f = QFont(Fonts.FAMILY, int(9 * Fonts.TEXT_SCALE))
        f.setBold(True)
        return f

    @staticmethod
    def label() -> QFont:
        return QFont(Fonts.FAMILY, int(8 * Fonts.TEXT_SCALE))

    @staticmethod
    def value() -> QFont:
        f = QFont(Fonts.FAMILY_MONO, int(10 * Fonts.TEXT_SCALE))
        f.setBold(True)
        return f

    @staticmethod
    def small() -> QFont:
        return QFont(Fonts.FAMILY, int(7 * Fonts.TEXT_SCALE))

    @staticmethod
    def vu_scale() -> QFont:
        f = QFont(Fonts.FAMILY, int(7 * Fonts.TEXT_SCALE))
        f.setBold(True)
        return f


def build_stylesheet() -> str:
    """Generate global Qt stylesheet."""
    return f"""
    * {{
        color: {Colors.TEXT};
        font-family: "{Fonts.FAMILY}";
        font-size: 9pt;
    }}
    QMainWindow, QWidget#centralWidget {{
        background: {Colors.BG_DARKEST};
    }}
    QSplitter {{
        background: {"transparent" if "Transparent" in _current_theme or "Glass" in _current_theme else Colors.BG_DARKEST};
    }}
    QComboBox {{
        background: {Colors.BG_INPUT};
        border: 1px solid {Colors.BORDER};
        border-radius: 3px;
        padding: 3px 8px;
        min-height: 18px;
    }}
    QLineEdit {{
        background: {Colors.BG_INPUT};
        border: 1px solid {Colors.BORDER};
        border-radius: 3px;
        color: {Colors.TEXT};
        padding: 2px 4px;
    }}
    QComboBox:hover {{
        border-color: {Colors.ACCENT_DIM};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 16px;
    }}
    QSlider::groove:horizontal {{
        background: {Colors.BG_INPUT};
        height: 4px;
        border-radius: 2px;
    }}
    QSlider::handle:horizontal {{
        background: {Colors.ACCENT};
        width: 12px;
        height: 12px;
        margin: -4px 0;
        border-radius: 6px;
    }}
    QSlider::handle:horizontal:hover {{
        background: {Colors.TEXT_BRIGHT};
    }}
    QCheckBox {{
        spacing: 6px;
    }}
    QCheckBox::indicator {{
        width: 14px;
        height: 14px;
        border: 1px solid {Colors.BORDER};
        border-radius: 3px;
        background: {Colors.BG_INPUT};
    }}
    QCheckBox::indicator:checked {{
        background: {Colors.ACCENT};
        border-color: {Colors.ACCENT};
    }}
    QPushButton {{
        background: {Colors.BG_SETTINGS};
        border: 1px solid {Colors.BORDER};
        border-radius: 3px;
        padding: 4px 12px;
        min-height: 18px;
    }}
    QPushButton:hover {{
        background: {Colors.BG_INPUT};
        border-color: {Colors.ACCENT_DIM};
    }}
    QLabel {{
        color: {Colors.TEXT_DIM};
        font-size: 8pt;
    }}
    QScrollArea {{
        border: none;
        background: transparent;
    }}
    QComboBox QAbstractItemView {{
        background: {Colors.BG_SETTINGS};
        border: 1px solid {Colors.BORDER_ACCENT};
        selection-background-color: {Colors.ACCENT_DIM};
        color: {Colors.TEXT};
    }}
    QMenu {{
        background: {Colors.BG_SETTINGS};
        border: 1px solid {Colors.BORDER_ACCENT};
        padding: 4px;
        color: {Colors.TEXT};
    }}
    QMenu::item {{
        padding: 5px 20px;
        border-radius: 3px;
        color: {Colors.TEXT};
    }}
    QMenu::item:selected {{
        background: {Colors.ACCENT_DIM};
        color: {Colors.TEXT_BRIGHT};
    }}
    QMenu::separator {{
        height: 1px;
        background: {Colors.BORDER};
        margin: 4px 8px;
    }}
    QToolTip {{
        background: {Colors.BG_SETTINGS};
        border: 1px solid {Colors.BORDER_ACCENT};
        color: {Colors.TEXT};
        padding: 4px;
    }}
    """
