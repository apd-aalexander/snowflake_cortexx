# snowflake_cortexx

A lightweight CLI wrapper + optional web UI for managing Snowflake Cortex CLI conversations.

This tool improves session management by allowing you to list, search, rename, delete, and resume conversations more intuitively. It is designed to improve session navigation, search, and organization without replacing the Cortex CLI itself.

---

# Installation

## 1. Clone repo

### macOS / Linux

```bash
mkdir -p ~/.local/bin
cd ~/.local/bin
git clone <your-repo> snowflake_cortexx
```

### Windows (PowerShell)

```powershell
mkdir $HOME\.local\bin
cd $HOME\.local\bin
git clone <your-repo> snowflake_cortexx
```

---

## 2. Python Requirements

* Python 3.9+ (CLI)
* Python 3.11+ (Web UI recommended)

Check:

```bash
python --version
```

---

## 3. Install Dependencies

```bash
pip install typer rich
```

---

## 4. Install fzf (Required for best experience)

### macOS

```bash
brew install fzf
```

### Linux

```bash
sudo apt install fzf
```

### Windows

Using winget:

```powershell
winget install fzf
```

Or Chocolatey:

```powershell
choco install fzf
```

---

## 5. Setup

### Option 1: Alias (quick)

#### macOS / Linux

```bash
alias cortexx="python3 ~/.local/bin/snowflake_cortexx/cli.py"
```

#### Windows (PowerShell)

```powershell
function cortexx {
    python $HOME\.local\bin\snowflake_cortexx\cli.py $args
}
```

---

### Option 2: Executable (recommended)

#### macOS / Linux

```bash
touch ~/.local/bin/cortexx
chmod +x ~/.local/bin/cortexx
```

```bash
#!/usr/bin/env python3
from cli import app
app()
```

---

#### Windows

Create `cortexx.bat`:

```bat
@echo off
python %USERPROFILE%\.local\bin\snowflake_cortexx\cli.py %*
```

---

## 5. Ensure PATH includes:

```bash
~/.local/bin
```

---


## 📁 Directory Structure

```
snowflake_cortexx/
 ├── cli.py          # CLI entry point
 ├── sessions.py     # Session management (list, rename, delete)
 ├── search.py       # Search functionality
 ├── utils.py        # Cortex CLI wrappers
 ├── config.py       # Paths and constants
 └── web/
     └── cortex_sessions.py   # optional web UI
```

---

## Usage

### List Sessions

```
cortexx list
```

Displays all sessions sorted by most recently updated.

---

## Open Session (Interactive)

```
cortexx open
```

Uses `fzf` to select a session.

---

### Open Session by Index

```
cortexx open <index>
```

Resumes a session by its index from the list.

---

### Continue Last Session

```
cortexx last
```

Equivalent to:

```
cortex --continue
```

---

### Rename Session

```
cortexx rename <index> "New Title"
```

---

### Archive Session (Safe Delete)

```
cortexx delete <index>
```

Moves session to:

```text
~/.snowflake/cortex/archive/
```

---

### Search Sessions

```
cortexx search <keyword>
```

Searches across all session content.

---

## 🌐 Launch Web UI

```
cortexx web
```

Or manually:

```
python web/cortex_sessions.py
```

Then open:

```text
http://127.0.0.1:8470
```

---

## Notes

* Sessions are stored in:

  ```
  ~/.snowflake/cortex/conversations/
  ```
* Files are JSON and can be edited manually if needed
* UTF-8 encoding is required for proper parsing
* Be careful not to corrupt session files
* Indexes change dynamically — always re-run `list`
* Archive is reversible (move file back to conversations)

---

## Troubleshooting

### No sessions showing

* Check path: `~/.snowflake/cortex/conversations/`
* Ensure files exist and are valid JSON

### Encoding errors

* Ensure files are opened with `encoding="utf-8"`

