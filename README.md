# LoLQ

Auto-pick champions, spells, and runes in League of Legends. Configure everything through a simple web page.

![Config Editor](lolq-ui.png)

## Setup

### 1. Install Python (skip if you already have it)

A Python installer is included in this repo: **`python-3.13.1-amd64.exe`**

Double-click it and follow the prompts. **Make sure to check "Add Python to PATH"** during installation.

To check if Python is already installed, open Command Prompt and type:
```
python --version
```
If you see a version number (3.x), you're good to go.

### 2. Install dependencies

Open Command Prompt in the LoLQ folder and run:
```
pip install -r requirements.txt
```

### 3. Run LoLQ

```
python start.py
```

This does two things:
- Opens a config editor in your browser at **http://localhost:5005**
- Starts the autopicker that connects to your League client

### 4. Configure your picks

In the browser page that opens:

- **Bans** - Set which champions to auto-ban
- **Layouts** - Create champion configs (champion + spells + runes)
- **Roles** - Drag layouts into roles so the right champion is picked for each position
- **Fallback** - Choose what happens if your role has no layout set

All changes save automatically. No save button needed.

### 5. Play

Leave LoLQ running. When you enter champion select, it will:
1. Auto-accept the queue
2. Ban your configured champion
3. Pick the right champion for your assigned role
4. Set your summoner spells
5. Set your runes

Press **Ctrl+C** in the terminal to stop LoLQ.

## Command Line Options

```
python start.py           # Start everything (recommended)
python start.py --editor  # Config editor only (no autopicker)
python start.py --picker  # Autopicker only (no web UI)
```

## Requirements

- Windows (League of Legends must be installed)
- Python 3.6+
- League client must be running for the autopicker to connect
