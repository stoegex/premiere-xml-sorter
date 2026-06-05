# XML Sorter v3.2

Eine Python-Anwendung mit grafischer Oberfläche, die Premiere-Pro-/XMEML-Timelines nach dem Dateidatum der Videoquellen sortiert.

## Funktionen

- Sortiert Video-Clips chronologisch nach dem Datum ihrer Quelldatei
- Verschiebt verknüpfte Video- und Audio-Clips als gemeinsame Gruppe
- Erkennt eindeutig zuordenbares, nicht verknüpftes Mikrofon-Audio anhand seiner Timeline-Position und verschiebt es mit dem Video
- Lässt mehrdeutiges, nicht verknüpftes Audio unverändert, damit keine falsche Zuordnung entsteht
- Verarbeitet mehrere Sequenzen innerhalb einer XML getrennt
- Aktualisiert die XML-Link-Indizes nach dem Umsortieren
- Unterstützt Dateiauswahl und optional Drag & Drop
- Enthält Startdateien für macOS und Windows

## Unterstütztes Format

Das Tool verarbeitet Premiere-Pro-/Final-Cut-Pro-7-XML im XMEML-Aufbau:

```text
sequence > media > video/audio > track > clipitem
```

Moderne Final-Cut-Pro-FCPXML-Dateien verwenden eine andere Struktur und werden aktuell nicht vollständig unterstützt.

## Voraussetzungen

- Python 3.7 oder neuer
- `customtkinter`
- `tkinterdnd2` optional für Drag & Drop

Installation:

```bash
python3 -m pip install customtkinter tkinterdnd2
```

Unter Windows kann statt `python3` auch `py -3` verwendet werden.

## Starten

### macOS

`start.command` per Doppelklick öffnen oder im Terminal starten:

```bash
./start.command
```

Falls macOS die Datei beim ersten Start blockiert, kann sie über Rechtsklick und **Öffnen** gestartet werden.

### Windows

`start.bat` per Doppelklick öffnen.

### Linux oder direkt über Python

```bash
python3 xml-sorter.py
```

## Ablauf

1. XML-Datei auswählen oder in das Fenster ziehen.
2. Das Tool liest Sequenzen, Tracks, Clip-Links und vorhandene Quelldateien.
3. Das Sortierdatum wird ausschließlich von der Videoquelle bestimmt.
4. Explizit verknüpftes Audio wird als Teil derselben Gruppe verschoben.
5. Nicht verknüpftes Audio wird nur dann mitverschoben, wenn die Timeline-Zuordnung zu einem Video eindeutig ist.
6. Mehrdeutiges Audio bleibt an seiner ursprünglichen Position und wird im Log gemeldet.
7. Das Ergebnis wird neben der Originaldatei als `<name>_sorted.xml` gespeichert.

Die Originaldatei wird nicht überschrieben.

## Datumsbestimmung

Das Tool verwendet den Dateisystem-Zeitstempel der gefundenen Videoquelldatei:

- Windows und Linux: `st_mtime`
- macOS: der frühere Wert aus `st_birthtime` und `st_mtime`

Audio-Dateien werden nicht für die chronologische Sortierung ausgewertet. Kopieren, Transkodieren oder Bearbeiten einer Videodatei kann deren Zeitstempel verändern und damit die Sortierreihenfolge beeinflussen.

## Verhalten bei Audio

Priorität der Audio-Zuordnung:

1. Vorhandene XML-Links über `linkclipref` oder `mediatype`, `trackindex` und `clipindex`
2. Eindeutige zeitliche Zuordnung, beispielsweise identischer Start und identisches Ende
3. Keine Zuordnung bei mehreren gleichwertigen Kandidaten

Die automatische zeitliche Zuordnung erzeugt keine neue permanente XML-Verknüpfung. Sie sorgt nur dafür, dass das Audio beim Sortieren denselben Versatz wie das erkannte Video erhält.

## Bekannte Grenzen

- Komplexe Timelines mit parallelen Video-Layern, Overlays oder Multicam-Strukturen können durch die chronologische Linearisierung ihre ursprüngliche Anordnung verlieren.
- Nicht eindeutig zuordenbares Audio wird aus Sicherheitsgründen nicht verschoben.
- Fehlende oder nicht erreichbare Medienpfade verhindern eine zuverlässige Datumsbestimmung.
- Moderne FCPXML-Strukturen werden nicht vollständig unterstützt.

Vor dem produktiven Einsatz sollte die erzeugte XML in einem neuen Premiere-Pro-Projekt importiert und kontrolliert werden.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

Die Tests decken verknüpftes Audio, eindeutig zuordenbares externes Audio, mehrdeutiges Audio und mehrere Sequenzen ab.

## Lizenz

MIT

## Autor

stoegex
