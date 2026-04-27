# snowflake_cortexx

A lightweight CLI wrapper for managing Snowflake Cortex CLI conversations.

This tool improves session management by allowing you to list, search, rename, delete, and resume conversations more intuitively.

---

## Installation

Clone or place this repo somewhere accessible, e.g.:

```
~/.local/bin/snowflake_cortexx/
```

Then create an alias:

```
alias cortexx="python ~/.local/bin/snowflake_cortexx/cli.py"
```

(Optional) Add to your shell config (`.bashrc`, `.zshrc`, etc.)

---

## 📁 Directory Structure

```
cortexx/
 ├── cli.py          # CLI entry point
 ├── sessions.py     # Session management (list, rename, delete)
 ├── search.py       # Search functionality
 ├── utils.py        # Cortex CLI wrappers
 ├── config.py       # Paths and constants
```

---

## Usage

### List Sessions

```
cortexx list
```

Displays all sessions sorted by most recently updated.

---

### Open Session

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

### Delete Session

```
cortexx delete <index>
```

This permanently deletes the session file.

---

### Search Sessions

```
cortexx search <keyword>
```

Searches across all session content.

---

## Notes

* Sessions are stored in:

  ```
  ~/.snowflake/cortex/conversations/
  ```
* Files are JSON and can be edited manually if needed
* UTF-8 encoding is required for proper parsing
* Be careful not to corrupt session files

---

## Troubleshooting

### No sessions showing

* Check path: `~/.snowflake/cortex/conversations/`
* Ensure files exist and are valid JSON

### Encoding errors

* Ensure files are opened with `encoding="utf-8"`

