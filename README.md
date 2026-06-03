# XML Sorter v3.1

A Python-based GUI application that sorts Premiere/FCP XML timelines by creation date.

## Features

- 🎬 **Sorts XML Timelines**: Automatically sorts Premiere Pro / Final Cut Pro XML files by creation date
- 🎨 **Modern GUI**: Clean, dark-themed interface built with customtkinter
- 🖱️ **Drag & Drop Support**: Drop XML files directly onto the application (requires tkinterdnd2)
- 📅 **Smart Date Detection**: Uses file modification time to detect camera recording dates
- 🖥️ **Cross-Platform**: Works on Windows, macOS, and Linux

## Requirements

- Python 3.7+
- `customtkinter` - Modern GUI library
- `tkinterdnd2` (optional) - For drag & drop functionality

## Installation

1. Clone the repository:
```bash
git clone https://github.com/stoegex/xml-sorter.git
cd xml-sorter
```

2. Install dependencies:
```bash
pip install customtkinter tkinterdnd2
```

## Usage

### Windows
Simply run the batch file:
```bash
start.bat
```

### macOS / Linux
```bash
python3 xml-sorter.py
```

## How It Works

1. Load or drag an XML timeline file
2. The application parses the XML structure
3. Clips are sorted by their creation date (stored in file metadata)
4. The sorted timeline is saved

## Notes

- The application uses `st_mtime` (modification time) to detect creation dates, which preserves camera recording dates even after file transfer
- On Windows, `st_ctime` is the file copy date, not the recording date, so `st_mtime` is used instead

## License

MIT

## Author

stoegex
