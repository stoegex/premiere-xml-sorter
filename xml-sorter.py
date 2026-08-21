#!/usr/bin/env python3
"""
FCP XML Sorter v3.3 – Sortiert Premiere/FCP XML Timelines nach Aufnahmezeit.
"""
import xml.etree.ElementTree as ET
import customtkinter as ctk
from tkinter import filedialog
import os
from datetime import datetime
from xml_sorter_core import (
    analyze_xml,
    find_child,
    format_camera_offsets,
    indent,
    parse_camera_offsets,
    parse_with_repair,
    sort_sequences,
)

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
        self.window.geometry("800x670")
        self.window.minsize(680, 560)
        self.window.configure(fg_color=C_BG)

        # Fenster zentrieren
        self.window.update_idletasks()
        sw = self.window.winfo_screenwidth()
        sh = self.window.winfo_screenheight()
        self.window.geometry(f"800x670+{(sw - 800)//2}+{(sh - 670)//2}")

        self.filepath = None
        self.tree = None
        self.sequence_contexts = []
        self.total_clips = 0
        self.files_found = 0
        self.files_missing = 0
        self.mapping = {}
        self.camera_offsets = {}

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
            hdr, text="Sortiert Clips nach Aufnahmezeit der Videoquelle  ·  aufsteigend",
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

        self.camera_offset_btn = ctk.CTkButton(
            btm, text="⏱  Kamera-Uhr korrigieren",
            font=ctk.CTkFont(family="Arial", size=11),
            fg_color=C_SURFACE, hover_color=C_CARD, text_color=C_TEXT2,
            corner_radius=8, height=28, width=190,
            command=self._edit_camera_offsets,
        )
        self.camera_offset_btn.grid(row=3, column=0, sticky="w", pady=(0, 6))

        # Fortschrittsbalken (schlank, immer sichtbar)
        self.progress = ctk.CTkProgressBar(
            btm, progress_color=C_ACCENT, fg_color=C_SURFACE,
            height=5, corner_radius=3, mode="indeterminate",
        )
        self.progress.grid(row=4, column=0, sticky="ew", pady=(0, 8))
        self.progress.set(0)

        # Sortier-Button
        self.sort_btn = ctk.CTkButton(
            btm, text="\u2728  Sortieren & Speichern",
            font=ctk.CTkFont(family="Arial", size=14, weight="bold"),
            fg_color=C_ACCENT, hover_color=C_ACCENT_H,
            corner_radius=12, height=44, state="disabled",
            command=self._sort_and_save,
        )
        self.sort_btn.grid(row=5, column=0, sticky="ew", pady=(0, 8))

        # Ergebnis-Label
        self.stats_label = ctk.CTkLabel(
            btm, text="",
            font=ctk.CTkFont(family="Arial", size=12),
            text_color=C_SUCCESS, wraplength=700, justify="left", anchor="w",
        )
        self.stats_label.grid(row=6, column=0, sticky="ew", pady=(0, 2))

        self.error_label = ctk.CTkLabel(
            btm, text="",
            font=ctk.CTkFont(family="Arial", size=12),
            text_color=C_ERROR, wraplength=700, justify="left", anchor="w",
        )
        self.error_label.grid(row=7, column=0, sticky="ew", pady=(0, 4))

        # Log-Bereich
        ctk.CTkLabel(
            btm, text="LOG",
            font=ctk.CTkFont(family="Courier New", size=9, weight="bold"),
            text_color=C_MUTED, anchor="w",
        ).grid(row=8, column=0, sticky="w", pady=(0, 2))

        self.log_text = ctk.CTkTextbox(
            btm,
            font=ctk.CTkFont(family="Courier New", size=10),
            fg_color=C_LOG_BG, text_color=C_LOG_TEXT,
            corner_radius=8, height=80, activate_scrollbars=True,
        )
        self.log_text.grid(row=9, column=0, sticky="ew")
        self.log_text.configure(state="disabled")

    def _hover(self, entering: bool) -> None:
        if entering:
            self.drop_frame.configure(border_color=C_ACCENT_L)
            self.dz_main.configure(text_color=C_ACCENT_L)
        else:
            bc = C_ACCENT_H if self.filepath else C_ACCENT
            self.drop_frame.configure(border_color=bc)
            self.dz_main.configure(text_color=C_TEXT2)

    def _edit_camera_offsets(self):
        dialog = ctk.CTkToplevel(self.window)
        dialog.title("Kamera-Uhr korrigieren")
        dialog.geometry("540x360")
        dialog.resizable(False, False)
        dialog.transient(self.window)
        dialog.grab_set()
        dialog.configure(fg_color=C_BG)
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(1, weight=1)

        ctk.CTkLabel(
            dialog,
            text=(
                "Zeitkorrekturen je Kamera/Ordner. Eine Regel pro Zeile:\n"
                "Pfadteil = +/-HH:MM     Beispiel: 00_S1II = +01:00"
            ),
            font=ctk.CTkFont(family="Arial", size=12),
            text_color=C_TEXT2, justify="left", anchor="w",
        ).grid(row=0, column=0, padx=22, pady=(22, 10), sticky="ew")

        editor = ctk.CTkTextbox(
            dialog, font=ctk.CTkFont(family="Consolas", size=12),
            fg_color=C_LOG_BG, text_color=C_TEXT1, corner_radius=8,
        )
        editor.grid(row=1, column=0, padx=22, pady=(0, 8), sticky="nsew")
        editor.insert("1.0", format_camera_offsets(self.camera_offsets))

        feedback = ctk.CTkLabel(
            dialog, text="", font=ctk.CTkFont(size=11), text_color=C_ERROR, anchor="w",
        )
        feedback.grid(row=2, column=0, padx=22, pady=(0, 6), sticky="ew")

        buttons = ctk.CTkFrame(dialog, fg_color="transparent")
        buttons.grid(row=3, column=0, padx=22, pady=(0, 20), sticky="e")

        def save_offsets():
            try:
                self.camera_offsets = parse_camera_offsets(editor.get("1.0", "end-1c"))
            except ValueError as error:
                feedback.configure(text=str(error))
                return
            dialog.destroy()
            if self.filepath:
                self._load_xml()

        ctk.CTkButton(
            buttons, text="Abbrechen", width=100, fg_color=C_SURFACE,
            hover_color=C_CARD, command=dialog.destroy,
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            buttons, text="Übernehmen", width=110, fg_color=C_ACCENT,
            hover_color=C_ACCENT_H, command=save_offsets,
        ).pack(side="left")

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
        self.sequence_contexts = []
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
            self.tree, repaired = parse_with_repair(self.filepath, logger=self.log)
            root = self.tree.getroot()
            if repaired:
                self.log("[Warnung] XML-Datei wurde repariert, da sie unvollständig war (Clips könnten fehlen).")
        except Exception as e:
            self._show_error(f"{e}")
            return

        base_dir = os.path.dirname(os.path.abspath(self.filepath))
        analysis = analyze_xml(root, base_dir, self.mapping, self.camera_offsets)
        self.sequence_contexts = analysis["sequences"]
        self.total_clips = analysis["video_clip_count"]
        self.files_found = analysis["total_found"]
        self.files_missing = analysis["total_missing"]

        self.log(f"File-Registry: {analysis['file_registry_count']} eindeutige Quelldateien gefunden")
        self.log(f"Sequenzen: {len(self.sequence_contexts)}")
        self.log(
            f"Video-Clips: {self.total_clips} ({self.files_found} mit Datum, {self.files_missing} ohne)"
        )
        self.log(
            f"Zeitquelle: {analysis['gopro_original_360_date_count']} GoPro-Original-360, "
            f"{analysis['embedded_date_count']} eingebettete Metadaten, "
            f"{analysis['filesystem_date_count']} Dateisystem-Fallbacks"
        )
        if analysis["offset_clip_count"]:
            self.log(f"Kamera-Uhrkorrektur auf {analysis['offset_clip_count']} Video-Clips angewendet")
        self.log(
            f"Audio-Clips: {analysis['audio_clip_count']} (werden link-basiert synchron verschoben)"
        )

        if analysis["warnings"]:
            shown = analysis["warnings"][:5]
            for warning in shown:
                self.log(f"[Warnung] {warning}")
            if len(analysis["warnings"]) > len(shown):
                self.log(f"[Warnung] {len(analysis['warnings']) - len(shown)} weitere Link-Warnungen")

        fname = os.path.basename(self.filepath)
        n_audio = analysis["audio_clip_count"]

        # Drop-Zone aktualisieren
        self.dz_icon.configure(text="\u2705")
        self.dz_main.configure(text=f"{fname}", text_color=C_ACCENT_L)
        self.dz_hint.configure(text=f"{self.total_clips} Video-Clips  \u00b7  {n_audio} Audio-Clips")
        self.drop_frame.configure(border_color=C_ACCENT_H)

        # Status-Dot
        self.st_dot.configure(text="\u25cf ", text_color=C_ACCENT)
        self.status_label.configure(
            text=f"{self.total_clips} Video-Clips in {len(self.sequence_contexts)} Sequenzen geladen",
            text_color=C_ACCENT_L
        )

        if self.files_found > 0:
            if analysis["all_dates"]:
                self.info_label.configure(
                    text=(
                        f"Fr\u00fchestes: {min(analysis['all_dates']):%Y-%m-%d %H:%M}   "
                        f"Sp\u00e4testes: {max(analysis['all_dates']):%Y-%m-%d %H:%M}"
                    ),
                    text_color=C_MUTED
                )
        else:
            self.log(f"Keine Datei gefunden ({self.files_missing} Pfade fehlen)")
            if analysis["macos_paths"]:
                self.log("macOS-Pfade erkannt! (Die Dateien m\u00fcssen auf diesem PC auffindbar sein)")
            else:
                self.log("Keine Dateien gefunden. \u00dcberpr\u00fcfe die Pfade in der XML.")

        notices = []
        if self.camera_offsets:
            notices.append(f"Kamera-Uhrkorrektur aktiv: {format_camera_offsets(self.camera_offsets).replace(chr(10), '  ·  ')}")
        if self.mapping:
            notices.append(f"Pfad-Mapping aktiv: {self.mapping}")
        if notices:
            self.mapping_label.configure(text="  ·  ".join(notices))
        if self.total_clips > 0:
            self.sort_btn.configure(state="normal")
        else:
            self._show_error("Keine Video-Clips gefunden.")

    def _sort_and_save(self):
        if not self.filepath or not self.sequence_contexts:
            return

        self.progress.start()
        self.sort_btn.configure(state="disabled", text="\u23f3  Sortiere...")
        self.window.update()

        self.log("\nSortiere Clips ...")

        sort_stats = sort_sequences(self.sequence_contexts)
        self.log(
            f"Sequenzen sortiert: {sort_stats['sequence_count']}  ·  Gruppen: {sort_stats['group_count']}  ·  verschoben: {sort_stats['moved_groups']}"
        )
        if sort_stats["inferred_audio_clips"]:
            self.log(
                f"[Hinweis] {sort_stats['inferred_audio_clips']} unverknoepfte Audio-Clips wurden ueber Timeline-Logik einem Video zugeordnet und mitverschoben"
            )
        if sort_stats["unlinked_audio_clips"]:
            self.log(
                f"[Hinweis] {sort_stats['unlinked_audio_clips']} unverknoepfte Audio-Clips blieben an ihrer Originalposition"
            )

        # 6. Bin-Struktur fuer Premiere Pro anlegen
        root = self.tree.getroot()
        if find_child(root, 'project') is None:
            sequences = [elem for elem in list(root) if elem.tag == 'sequence' or elem.tag.endswith('}sequence')]
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
