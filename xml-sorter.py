#!/usr/bin/env python3
"""
FCP XML Sorter v3.1 – Sortiert Premiere/FCP XML Timelines nach Erstellungsdatum.
"""
import xml.etree.ElementTree as ET
import customtkinter as ctk
from tkinter import filedialog
import os
import platform
import urllib.parse
from datetime import datetime

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    HAS_DND = True
except ImportError:
    HAS_DND = False

# ── Farbschema ────────────────────────────────────────────────────────────────
C_ACCENT   = "#8B5CF6"
C_ACCENT_H = "#7C3AED"
C_ACCENT_L = "#A78BFA"
C_BG       = "#0E0E12"
C_CARD     = "#18181D"
C_SURFACE  = "#24242C"
C_DROP_BG  = "#11111A"
C_TEXT1    = "#F3F4F6"
C_TEXT2    = "#9CA3AF"
C_MUTED    = "#6B7280"
C_SUCCESS  = "#10B981"
C_WARN     = "#F59E0B"
C_ERROR    = "#EF4444"
C_LOG_BG   = "#0B0B0E"
C_LOG_TEXT = "#4B5563"

# ----------------------------------------------------------------------
# Hilfsfunktionen
# ----------------------------------------------------------------------
def get_file_creation_date(filepath):
    """Aufnahmedatum einer Datei.
    Verwendet st_mtime (Kamera-Aufnahmedatum wird als modification time gespeichert).
    st_ctime ist auf Windows das Kopier-Datum, NICHT das Aufnahmedatum!
    Fallback: st_birthtime (macOS), dann st_ctime.
    """
    if not filepath or not os.path.exists(filepath):
        return None
    try:
        stat = os.stat(filepath)
        # st_mtime = Aufnahmedatum der Kamera (bleibt beim Kopieren erhalten)
        # st_ctime = auf Windows: Datum des Kopierens (FALSCH fuer Sortierung)
        # st_birthtime = macOS: echtes Erstellungsdatum
        if hasattr(stat, 'st_birthtime'):
            # macOS: nimm das frueheste von birthtime und mtime
            birth = datetime.fromtimestamp(stat.st_birthtime)
            mtime = datetime.fromtimestamp(stat.st_mtime)
            return min(birth, mtime)
        else:
            # Windows: st_mtime ist das echte Kamera-Aufnahmedatum
            return datetime.fromtimestamp(stat.st_mtime)
    except Exception as e:
        print(f"  [Warnung] Fehler beim Lesen von {filepath}: {e}")
        return None

def resolve_path(url_str, base_dir, mapping=None):
    """Wandelt file://URL oder relativen Pfad in absoluten Pfad um.
       mapping: dict { '/Volumes/LUMIX': 'H:\\LUMIX' } zum Ersetzen von Pfadanfängen.
    """
    if not url_str:
        return None
    url_str = urllib.parse.unquote(url_str.strip())
    if url_str.startswith('file://'):
        parsed = urllib.parse.urlparse(url_str)
        path = parsed.path
        if platform.system() == 'Windows' and path.startswith('/'):
            path = path[1:]
        if not path and parsed.netloc:
            path = parsed.netloc
    else:
        path = url_str

    # Pfad-Mapping anwenden (vor Normalisierung)
    if mapping:
        for old, new in mapping.items():
            if path.startswith(old):
                path = new + path[len(old):]
                break

    if os.path.isabs(path):
        return os.path.normpath(path)
    return os.path.normpath(os.path.join(base_dir, path))

def find_all_file_paths(clipitem, base_dir, mapping=None):
    """Findet alle Pfade in einem Clipitem (Namespace-unabhängig)."""
    found = []
    added = set()
    def add(resolved, source):
        if resolved and resolved not in added:
            added.add(resolved)
            found.append((resolved, source))

    # Alle <file> Elemente (Namespace-Wildcard)
    for file_elem in clipitem.findall('.//{*}file'):
        # pathurl
        for pathurl in file_elem.findall('{*}pathurl'):
            if pathurl.text:
                add(resolve_path(pathurl.text.strip(), base_dir, mapping), 'file/pathurl')
        # name
        for name in file_elem.findall('{*}name'):
            if name.text:
                add(resolve_path(name.text.strip(), base_dir, mapping), 'file/name')
        # url
        for url in file_elem.findall('{*}url'):
            if url.text:
                add(resolve_path(url.text.strip(), base_dir, mapping), 'file/url')

    # <link> -> <media> -> <file>
    for link in clipitem.findall('{*}link'):
        for file_elem in link.findall('.//{*}file'):
            for pathurl in file_elem.findall('{*}pathurl'):
                if pathurl.text:
                    add(resolve_path(pathurl.text.strip(), base_dir, mapping), 'link/…')

    return found

def indent(elem, level=0):
    """Pretty-Print für XML."""
    indent_str = "  "
    i = "\n" + level * indent_str
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + indent_str
        for child in elem:
            indent(child, level + 1)
            if not child.tail or not child.tail.strip():
                child.tail = i + indent_str
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = i

# ----------------------------------------------------------------------
# GUI-Klasse
# ----------------------------------------------------------------------
if HAS_DND:
    class TkinterDnD_CTk(ctk.CTk, TkinterDnD.DnDWrapper):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.TkdndVersion = TkinterDnD._require(self)
else:
    class TkinterDnD_CTk(ctk.CTk):
        pass

class FCPXMLSorter:
    def __init__(self):
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")
        self.window = TkinterDnD_CTk()
        self.window.title("FCP XML Sorter")
        self.window.geometry("800x620")
        self.window.minsize(680, 520)
        self.window.configure(fg_color=C_BG)

        # Fenster zentrieren
        self.window.update_idletasks()
        sw = self.window.winfo_screenwidth()
        sh = self.window.winfo_screenheight()
        self.window.geometry(f"800x620+{(sw - 800)//2}+{(sh - 620)//2}")

        self.filepath = None
        self.tree = None
        self.clips_data = {}
        self.total_clips = 0
        self.files_found = 0
        self.files_missing = 0
        self.mapping = {}
        self.audio_clips_data = {}

        self._build_ui()

    def _build_ui(self):
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(0, weight=1)

        outer = ctk.CTkFrame(self.window, fg_color=C_BG, corner_radius=0)
        outer.grid(row=0, column=0, sticky="nsew")
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(2, weight=1)

        # ── Titelbereich ──────────────────────────────────────────────────────
        hdr = ctk.CTkFrame(outer, fg_color="transparent")
        hdr.grid(row=0, column=0, padx=40, pady=(26, 0), sticky="ew")
        hdr.columnconfigure(0, weight=1)
        ctk.CTkLabel(
            hdr, text="FCP XML Sorter",
            font=ctk.CTkFont(family="Arial", size=26, weight="bold"),
            text_color=C_ACCENT,
        ).grid(row=0, column=0)
        ctk.CTkLabel(
            hdr, text="Sortiert Clips nach Erstellungsdatum der Quelldatei  ·  aufsteigend",
            font=ctk.CTkFont(family="Arial", size=12),
            text_color=C_MUTED,
        ).grid(row=1, column=0, pady=(3, 0))

        # ── Trennlinie ────────────────────────────────────────────────────────
        ctk.CTkFrame(outer, height=1, fg_color=C_SURFACE, corner_radius=0
                     ).grid(row=1, column=0, padx=40, pady=(16, 0), sticky="ew")

        # ── Drop-Zone ─────────────────────────────────────────────────────────
        self.drop_frame = ctk.CTkFrame(
            outer, corner_radius=15, fg_color=C_DROP_BG,
            border_width=2, border_color=C_ACCENT,
        )
        self.drop_frame.grid(row=2, column=0, padx=40, pady=(14, 0), sticky="nsew")
        self.drop_frame.columnconfigure(0, weight=1)
        self.drop_frame.rowconfigure(0, weight=1)

        dz_inner = ctk.CTkFrame(self.drop_frame, fg_color="transparent")
        dz_inner.grid(row=0, column=0)

        self.dz_icon = ctk.CTkLabel(dz_inner, text="\U0001f4c2",
                                    font=ctk.CTkFont(size=40))
        self.dz_icon.pack()

        dnd_text = ("Ziehe eine FCP XML hierher\noder klicke zum Ausw\u00e4hlen\n"
                    if not HAS_DND else
                    "Ziehe eine FCP XML hierher\noder klicke zum Ausw\u00e4hlen")
        self.dz_main = ctk.CTkLabel(
            dz_inner, text=dnd_text,
            font=ctk.CTkFont(family="Arial", size=14),
            text_color=C_TEXT2, justify="center",
        )
        self.dz_main.pack(pady=(9, 4))

        self.dz_hint = ctk.CTkLabel(
            dz_inner, text=".fcpxml  \u00b7  .xml",
            font=ctk.CTkFont(family="Arial", size=11),
            text_color=C_MUTED,
        )
        self.dz_hint.pack(pady=(0, 4))

        dnd_badge_text  = "\u26a1 Drag & Drop aktiv" if HAS_DND else "Klicken zum Ausw\u00e4hlen"
        dnd_badge_color = C_ACCENT_L if HAS_DND else C_MUTED
        self.dnd_badge = ctk.CTkLabel(
            dz_inner, text=dnd_badge_text,
            font=ctk.CTkFont(family="Arial", size=10),
            text_color=dnd_badge_color,
        )
        self.dnd_badge.pack(pady=(2, 0))

        # Klick + Hover an alle Drop-Widgets binden
        for w in [self.drop_frame, dz_inner, self.dz_icon, self.dz_main,
                  self.dz_hint, self.dnd_badge]:
            w.bind("<Button-1>", self._select_file)
            w.bind("<Enter>",    lambda e: self._hover(True))
            w.bind("<Leave>",    lambda e: self._hover(False))
            try: w.configure(cursor="hand2")
            except Exception: pass

        # DnD registrieren
        if HAS_DND:
            self.drop_frame.drop_target_register(DND_FILES)
            self.drop_frame.dnd_bind('<<Drop>>', self._on_drop)
            self.drop_frame.dnd_bind('<<DragEnter>>', lambda e: self._hover(True))
            self.drop_frame.dnd_bind('<<DragLeave>>', lambda e: self._hover(False))
            self.window.drop_target_register(DND_FILES)
            self.window.dnd_bind('<<Drop>>', self._on_drop)

        # ── Unterer Bereich ───────────────────────────────────────────────────
        btm = ctk.CTkFrame(outer, fg_color="transparent")
        btm.grid(row=3, column=0, padx=40, pady=(12, 22), sticky="ew")
        btm.columnconfigure(0, weight=1)

        # Status-Leiste
        status_bar = ctk.CTkFrame(btm, fg_color=C_CARD, corner_radius=10)
        status_bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        status_bar.columnconfigure(1, weight=1)
        self.st_dot = ctk.CTkLabel(
            status_bar, text="\u25cb ",
            font=ctk.CTkFont(size=11), text_color=C_MUTED, width=22,
        )
        self.st_dot.grid(row=0, column=0, padx=(12, 0), pady=8)
        self.status_label = ctk.CTkLabel(
            status_bar, text="Keine Datei geladen",
            font=ctk.CTkFont(family="Arial", size=12),
            text_color=C_MUTED, anchor="w",
        )
        self.status_label.grid(row=0, column=1, padx=(4, 12), pady=8, sticky="w")

        # Info-Zeile (Datum-Bereich)
        self.info_label = ctk.CTkLabel(
            btm, text="",
            font=ctk.CTkFont(family="Arial", size=11),
            text_color=C_MUTED, anchor="w",
        )
        self.info_label.grid(row=1, column=0, sticky="w", pady=(0, 2))

        # Mapping-Anzeige
        self.mapping_label = ctk.CTkLabel(
            btm, text="",
            font=ctk.CTkFont(family="Arial", size=11),
            text_color=C_WARN, anchor="w",
        )
        self.mapping_label.grid(row=2, column=0, sticky="w", pady=(0, 4))

        # Fortschrittsbalken (schlank, immer sichtbar)
        self.progress = ctk.CTkProgressBar(
            btm, progress_color=C_ACCENT, fg_color=C_SURFACE,
            height=5, corner_radius=3, mode="indeterminate",
        )
        self.progress.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        self.progress.set(0)

        # Sortier-Button
        self.sort_btn = ctk.CTkButton(
            btm, text="\u2728  Sortieren & Speichern",
            font=ctk.CTkFont(family="Arial", size=14, weight="bold"),
            fg_color=C_ACCENT, hover_color=C_ACCENT_H,
            corner_radius=12, height=44, state="disabled",
            command=self._sort_and_save,
        )
        self.sort_btn.grid(row=4, column=0, sticky="ew", pady=(0, 8))

        # Ergebnis-Label
        self.stats_label = ctk.CTkLabel(
            btm, text="",
            font=ctk.CTkFont(family="Arial", size=12),
            text_color=C_SUCCESS, wraplength=700, justify="left", anchor="w",
        )
        self.stats_label.grid(row=5, column=0, sticky="ew", pady=(0, 2))

        self.error_label = ctk.CTkLabel(
            btm, text="",
            font=ctk.CTkFont(family="Arial", size=12),
            text_color=C_ERROR, wraplength=700, justify="left", anchor="w",
        )
        self.error_label.grid(row=6, column=0, sticky="ew", pady=(0, 4))

        # Log-Bereich
        ctk.CTkLabel(
            btm, text="LOG",
            font=ctk.CTkFont(family="Courier New", size=9, weight="bold"),
            text_color=C_MUTED, anchor="w",
        ).grid(row=7, column=0, sticky="w", pady=(0, 2))

        self.log_text = ctk.CTkTextbox(
            btm,
            font=ctk.CTkFont(family="Courier New", size=10),
            fg_color=C_LOG_BG, text_color=C_LOG_TEXT,
            corner_radius=8, height=80, activate_scrollbars=True,
        )
        self.log_text.grid(row=8, column=0, sticky="ew")
        self.log_text.configure(state="disabled")

    def _hover(self, entering: bool) -> None:
        if entering:
            self.drop_frame.configure(border_color=C_ACCENT_L)
            self.dz_main.configure(text_color=C_ACCENT_L)
        else:
            bc = C_ACCENT_H if self.filepath else C_ACCENT
            self.drop_frame.configure(border_color=bc)
            self.dz_main.configure(text_color=C_TEXT2)

    def log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"{ts}  {msg}\n"
        print(line.rstrip())
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _select_file(self, event=None):
        path = filedialog.askopenfilename(
            title="FCP XML wählen",
            filetypes=[("FCP XML", "*.fcpxml *.xml"), ("Alle Dateien", "*.*")]
        )
        if path:
            self.filepath = path
            self.mapping = {}
            self._load_xml()

    def _on_drop(self, event):
        # event.data enthält den Pfad, der vom OS kommt.
        files = self.window.tk.splitlist(event.data)
        if files:
            path = files[0]
            if path:
                self.filepath = os.path.normpath(path)
                self.mapping = {}
                self._load_xml()

    def _load_xml(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
        self.status_label.configure(text="Lade ...", text_color=C_MUTED)
        self.st_dot.configure(text="○ ", text_color=C_MUTED)
        self.info_label.configure(text="")
        self.stats_label.configure(text="")
        self.error_label.configure(text="")
        self.sort_btn.configure(state="disabled")
        self.mapping_label.configure(text="")
        self.dz_icon.configure(text="\U0001f4c2")
        self.dz_main.configure(text="Ziehe eine FCP XML hierher\noder klicke zum Ausw\u00e4hlen", text_color=C_TEXT2)
        self.dz_hint.configure(text=".fcpxml  \u00b7  .xml")

        self.log("=" * 70)
        self.log("STARTE XML-ANALYSE")
        self.log(f"{os.path.basename(self.filepath)}")

        try:
            self.tree = ET.parse(self.filepath)
            root = self.tree.getroot()
        except Exception as e:
            self._show_error(f"{e}")
            return

        base_dir = os.path.dirname(os.path.abspath(self.filepath))

        sequences = root.findall('.//sequence')
        video_tracks = []
        audio_tracks = []
        for seq in sequences:
            media = seq.find('media')
            if media is None:
                continue
            video = media.find('video')
            if video is not None:
                video_tracks.extend(video.findall('track'))
            audio = media.find('audio')
            if audio is not None:
                audio_tracks.extend(audio.findall('track'))

        total_found = 0
        total_missing = 0
        all_dates = []
        macos_paths = set()

        # Premiere dedupliziert <file>-Elemente: die erste Erwaehnung enthaelt
        # die volle <pathurl>, alle weiteren nur noch <file id="file-XYZ"/>.
        # Wir bauen daher zuerst ein Register: file-id -> resolved path
        file_id_to_path = {}
        for file_elem in root.findall('.//file'):
            fid = file_elem.get('id')
            if not fid:
                continue
            for pathurl in file_elem.findall('pathurl'):
                if pathurl.text:
                    p = resolve_path(pathurl.text.strip(), base_dir, self.mapping)
                    if p:
                        file_id_to_path[fid] = p
                        break
            if fid not in file_id_to_path:
                # Versuche auch ohne Namespace-Wildcard
                for pathurl in file_elem.findall('{*}pathurl'):
                    if pathurl.text:
                        p = resolve_path(pathurl.text.strip(), base_dir, self.mapping)
                        if p:
                            file_id_to_path[fid] = p
                            break

        self.log(f"File-Registry: {len(file_id_to_path)} eindeutige Quelldateien gefunden")

        # Nur Video-Clips laden und Datum auslesen
        video_clips_data = {}
        for track in video_tracks:
            clipitems = track.findall('clipitem')
            if not clipitems:
                continue
            track_clips = []
            for clip in clipitems:
                # Pfad suchen: zuerst direkt im <file> Element, dann ueber File-Registry
                paths = find_all_file_paths(clip, base_dir, self.mapping)
                existing = next((p for p, s in paths if os.path.exists(p)), None)

                # Fallback: via file id in der Registry
                if not existing:
                    for file_elem in clip.findall('.//file'):
                        fid = file_elem.get('id')
                        if fid and fid in file_id_to_path:
                            p = file_id_to_path[fid]
                            if os.path.exists(p):
                                existing = p
                                break

                for p, src in paths:
                    if p and (p.startswith('/Volumes/') or p.startswith('/Users/')):
                        macos_paths.add(p)

                date = get_file_creation_date(existing) if existing else None
                if date:
                    all_dates.append(date)
                    total_found += 1
                else:
                    total_missing += 1
                track_clips.append({
                    'element': clip,
                    'date': date,
                    'path': existing,
                    'id': clip.get('id', '?'),
                })
            video_clips_data[track] = track_clips

        # Audio-Tracks separat speichern (kein Datum noetig)
        audio_clips_data = {}
        for track in audio_tracks:
            clipitems = track.findall('clipitem')
            if not clipitems:
                continue
            track_clips = []
            for clip in clipitems:
                track_clips.append({
                    'element': clip,
                    'id': clip.get('id', '?'),
                })
            audio_clips_data[track] = track_clips

        self.clips_data = video_clips_data
        self.audio_clips_data = audio_clips_data
        self.total_clips = sum(len(v) for v in video_clips_data.values())
        self.files_found = total_found
        self.files_missing = total_missing

        self.log(f"Video-Clips: {self.total_clips} ({total_found} mit Datum, {total_missing} ohne)")
        self.log(f"Audio-Clips: {sum(len(v) for v in audio_clips_data.values())} (werden automatisch synchron verschoben)")

        fname = os.path.basename(self.filepath)
        n_audio = sum(len(v) for v in audio_clips_data.values())

        # Drop-Zone aktualisieren
        self.dz_icon.configure(text="\u2705")
        self.dz_main.configure(text=f"{fname}", text_color=C_ACCENT_L)
        self.dz_hint.configure(text=f"{self.total_clips} Video-Clips  \u00b7  {n_audio} Audio-Clips")
        self.drop_frame.configure(border_color=C_ACCENT_H)

        # Status-Dot
        self.st_dot.configure(text="\u25cf ", text_color=C_ACCENT)
        self.status_label.configure(
            text=f"{self.total_clips} Video-Clips geladen, {total_found} mit Datum",
            text_color=C_ACCENT_L
        )

        if total_found > 0:
            if all_dates:
                self.info_label.configure(
                    text=f"Fr\u00fchestes: {min(all_dates):%Y-%m-%d %H:%M}   Sp\u00e4testes: {max(all_dates):%Y-%m-%d %H:%M}",
                    text_color=C_MUTED
                )
        else:
            self.log(f"Keine Datei gefunden ({total_missing} Pfade fehlen)")
            if macos_paths:
                self.log("macOS-Pfade erkannt! (Die Dateien m\u00fcssen auf diesem PC auffindbar sein)")
            else:
                self.log("Keine Dateien gefunden. \u00dcberpr\u00fcfe die Pfade in der XML.")

        if self.mapping:
            self.mapping_label.configure(text=f"Mapping aktiv: {self.mapping}")
        self.sort_btn.configure(state="normal")

    def _sort_and_save(self):
        if not self.filepath or not self.clips_data:
            return

        self.progress.start()
        self.sort_btn.configure(state="disabled", text="\u23f3  Sortiere...")
        self.window.update()

        self.log("\nSortiere Clips ...")

        def get_frame(element, tag):
            el = element.find(f'.//{{{"*"}}}{tag}')
            if el is None:
                el = element.find(tag)
            if el is not None and el.text:
                try: return int(el.text)
                except ValueError: return 0
            return 0

        def set_frame(element, tag, value):
            el = element.find(f'.//{{{"*"}}}{tag}')
            if el is None:
                el = element.find(tag)
            if el is not None:
                el.text = str(value)

        # 1. Alle Video-Clips flach sammeln (bereits in self.clips_data)
        all_video_clips = []
        for track, clips in self.clips_data.items():
            for c in clips:
                c['track'] = track
                c['orig_start'] = get_frame(c['element'], 'start')
                c['orig_end']   = get_frame(c['element'], 'end')
                all_video_clips.append(c)

        # 2. Video-Clips chronologisch sortieren (ohne Datum -> ans Ende)
        sorted_video = sorted(
            all_video_clips,
            key=lambda c: (c['date'] is None, c['date'] if c['date'] else datetime.max)
        )

        # 3. Neue Timeline-Positionen fuer Video-Clips berechnen
        #    und den Versatz (offset) pro Clip merken
        current_pos = 0
        for c in sorted_video:
            duration = c['orig_end'] - c['orig_start']
            c['new_start'] = current_pos
            c['new_end']   = current_pos + duration
            c['offset']    = c['new_start'] - c['orig_start']
            set_frame(c['element'], 'start', c['new_start'])
            set_frame(c['element'], 'end',   c['new_end'])
            current_pos += duration

        # 4. Audio-Clips verschieben: jeder Audio-Clip bekommt den Offset
        #    des Video-Clips, mit dem er sich am meisten ueberlappt
        all_audio_clips = []
        for track, clips in self.audio_clips_data.items():
            for c in clips:
                c['track'] = track
                c['orig_start'] = get_frame(c['element'], 'start')
                c['orig_end']   = get_frame(c['element'], 'end')
                all_audio_clips.append(c)

        for ac in all_audio_clips:
            best_offset = 0
            max_overlap = -1
            for vc in sorted_video:
                overlap = min(ac['orig_end'], vc['orig_end']) - max(ac['orig_start'], vc['orig_start'])
                if overlap > max_overlap:
                    max_overlap = overlap
                    best_offset = vc['offset']
            set_frame(ac['element'], 'start', ac['orig_start'] + best_offset)
            set_frame(ac['element'], 'end',   ac['orig_end']   + best_offset)

        # 5. XML-Reihenfolge der Clipitems innerhalb jedes Tracks anpassen
        for track, clips in self.clips_data.items():
            sorted_clips = sorted(clips, key=lambda c: get_frame(c['element'], 'start'))
            children = list(track)
            clip_indices = [i for i, child in enumerate(children)
                            if child.tag == 'clipitem' or child.tag.endswith('}clipitem')]
            for idx, c in zip(clip_indices, sorted_clips):
                children[idx] = c['element']
            track[:] = children

        for track, clips in self.audio_clips_data.items():
            sorted_clips = sorted(clips, key=lambda c: get_frame(c['element'], 'start'))
            children = list(track)
            clip_indices = [i for i, child in enumerate(children)
                            if child.tag == 'clipitem' or child.tag.endswith('}clipitem')]
            for idx, c in zip(clip_indices, sorted_clips):
                children[idx] = c['element']
            track[:] = children

        # 6. Bin-Struktur fuer Premiere Pro anlegen
        root = self.tree.getroot()
        if not root.find('project'):
            sequences = root.findall('sequence')
            if sequences:
                for seq in sequences:
                    root.remove(seq)
                project = ET.SubElement(root, 'project')
                proj_name = ET.SubElement(project, 'name')
                proj_name.text = "Sorted Project"
                proj_children = ET.SubElement(project, 'children')
                bin_el = ET.SubElement(proj_children, 'bin')
                bin_name_el = ET.SubElement(bin_el, 'name')
                base_name = os.path.splitext(os.path.basename(self.filepath))[0]
                bin_name_el.text = f"{base_name}_Sorted"
                bin_children = ET.SubElement(bin_el, 'children')
                for seq in sequences:
                    bin_children.append(seq)

        # 7. Speichern
        out = os.path.splitext(self.filepath)[0] + "_sorted.xml"
        try:
            indent(self.tree.getroot())
            self.tree.write(out, encoding='utf-8', xml_declaration=True)
            self.stats_label.configure(
                text=f"\u2705  Gespeichert: {os.path.basename(out)}",
                text_color=C_SUCCESS
            )
            self.error_label.configure(text="")
            self.log(f"Datei gespeichert: {out}")
            self.sort_btn.configure(
                state="normal",
                text="\u2728  Erneut sortieren",
                fg_color=C_ACCENT_H
            )
        except Exception as e:
            self._show_error(f"Fehler beim Speichern: {e}")
            self.sort_btn.configure(state="normal", text="\u2728  Sortieren & Speichern")

        self.progress.stop()
        self.progress.set(0)

    def _show_error(self, msg):
        self.error_label.configure(text=msg)
        self.log(msg)

    def run(self):
        self.window.mainloop()


if __name__ == "__main__":
    app = FCPXMLSorter()
    app.run()