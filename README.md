# A Tor Messenger Framework

**Metor** is a highly secure, Tor-based terminal messenger written in Python. It provides a persistent Tor Hidden Service (.onion address) along with an interactive, multiplexed live chat and asynchronous offline messaging.

Built on a robust **Client-Daemon Architecture** and structured via **Domain-Driven Design (DDD)**, the user interface is completely stateless. You can manage multiple secure connections simultaneously, maintain an address book, queue offline messages, and view connection history — all seamlessly from the console, whether running locally or remotely.

## 🌟 Key Features

- **Client-Daemon Architecture (Stateless UI):**
  The heavy lifting (Tor process management, cryptography, network sockets, outbox routing) runs in the background as a headless daemon. The Chat UI merely acts as a client communicating via a strictly typed IPC interface. You can close the UI at any time without dropping active Tor connections.
- **Asynchronous Offline Messaging ("Drops"):**
  Send messages even when your contact is offline. The daemon safely queues outgoing messages in a local SQLite Outbox and automatically delivers them in the background as soon as the peer comes online (Drop & Go).
- **Zero-Trace & Ephemeral Messages:**
  Configurable "Burn-After-Read" policies. Read messages can be permanently destroyed using cryptographic file shredding to meet strict OPSEC requirements.
- **Cryptographic Peer Authentication:**
  Connections are secured by a deterministic Ed25519 Challenge-Response handshake. Identity spoofing is mathematically impossible—every peer must cryptographically prove ownership of their `.onion` key before a session is established.
- **Multi-Profile Support:**
  Manage completely isolated identities (`metor -p work`, `metor -p private`). Each profile gets its own cryptographic keys, its own `.onion` address, and an isolated SQLCipher-encrypted database (Argon2i + SecretBox).
- **Dynamic Contact Management:**
  Unknown incoming connections are assigned volatile RAM aliases (e.g., `exw4kj1`) dynamically. These "Discovered Peers" can be promoted to permanent contacts on the fly. Deleting a contact during an active chat invokes a "Downgrade Delete"—the connection is not dropped, but gracefully downgraded back to a volatile alias.
- **Remote Capability (VPS / SSH):**
  Run the Metor daemon 24/7 on a secure remote server and securely connect your local laptop UI to it via an SSH tunnel forwarding the IPC port.

## 🏗️ Architecture & API

Metor strictly separates presentation (UI) from domain logic (Core/Data). Communication between the CLI and the background process occurs via rigidly defined **Data Transfer Objects (DTOs)**.

🔗 **Full API Reference:** Please review [API_DOCS.md](API_DOCS.md) for a comprehensive overview of all IPC Commands (UI -> Daemon) and Events (Daemon -> UI).

### OPSEC & Security Concepts

- **Data-at-Rest Encryption:** All local data (history, address book, queues) are stored in an SQLite database encrypted with `sqlcipher3`. Master keys are heavily derived using Argon2i and protected via NaCL SecretBoxes.
- **Network Anti-DoS:** Incoming TCP streams (both Tor and local IPC) enforce strict stream framing and length limitations (`MAX_STREAM_BYTES`) to thwart Out-Of-Memory (OOM) and UTF-8 fragmentation attacks.
- **Thread Safety:** Address book mutations and session state transitions are safeguarded by deterministic locks (`FileLock` across processes, `threading.Lock` in memory) preventing race conditions and database corruption.

## 🚀 Installation

For security reasons and to prevent supply-chain attacks, Metor **does not** bundle the Tor binary. You must install it from the official Tor Project sources.

### 1. Clone the Repository

```bash
# Clone the project to your local machine
git clone https://github.com/DerWahreMirakulix/metor.git

# Enter the repository
cd metor
```

### 2. Install Tor

- **Windows (Manual Security Install):** Download the [Tor Expert Bundle](https://www.torproject.org/download/tor/). Extract it and copy the `tor.exe` directly into your user directory under `C:\Users\YourName\.metor\tor.exe`.
- **Linux (Debian/Ubuntu):** `sudo apt update && sudo apt install tor`
- **Linux (Fedora):** `sudo dnf install tor`

### 3. Install the Python Package

Python 3.11 or higher is required.

```bash
# Standard installation
pip install .

# For developers (Editable Mode)
pip install -e .
```

## 💻 Usage & Commands

All data (databases, keys, configurations) are safely stored in your `~/.metor/` directory.
_Tip: Append `-p <profile_name>` to any command to use an isolated identity._

### 1. Start the Daemon

Before chatting, the background daemon must be started (and unlocked with a master password):

```bash
metor daemon
```

_Leave this terminal window running in the background, or use `tmux`/`screen`._

### 2. The Live Chat (Multiplexed UI)

Open a second terminal window to start the interactive user interface:

```bash
metor chat
```

Inside the Chat UI, you have access to the following slash commands:

| Command                         | Description                                                      |
| :------------------------------ | :--------------------------------------------------------------- |
| `/connect <onion\|alias>`       | Establishes a new secure Tor connection to a peer.               |
| `/accept [alias]`               | Accepts an incoming background connection request.               |
| `/reject [alias]`               | Rejects an incoming connection request.                          |
| `/switch [..\|alias]`           | Switches focus between active chats (use `..` to unfocus).       |
| `/end [alias]`                  | Terminates the connection to the specified peer.                 |
| `/fallback [alias]`             | Forces unacknowledged live messages into the offline drop queue. |
| `/contacts list`                | Displays the address book and temporary discovered peers.        |
| `/contacts add <alias> [onion]` | Saves a temporary RAM peer permanently to disk.                  |
| `/exit`                         | Closes the UI (the daemon remains active in the background).     |

### 3. Headless CLI Commands

You don't need to enter the Chat UI to use Metor. It can act as an asynchronous CLI messenger (similar to email).

| Command                        | Description                                                                  |
| :----------------------------- | :--------------------------------------------------------------------------- |
| `metor send <alias> "Message"` | Queues a message in the outbox (sent automatically when the peer is online). |
| `metor inbox`                  | Checks for new unread offline messages.                                      |
| `metor address show`           | Displays your current `.onion` hidden service address.                       |
| `metor contacts list`          | Lists your saved contacts.                                                   |
| `metor history show <alias>`   | Shows the connection event log for a specific peer.                          |
| `metor messages show <alias>`  | Prints the chat history with a contact directly to the console.              |

### 4. Profile Management & Remote Setup

Want to run Metor on a server and connect securely from your laptop?

1. **On the Server (VPS):** Run `metor profiles add my_server --port 50051` and start it with `metor -p my_server daemon`.
2. **On your Laptop:** Run `metor profiles add remote_node --remote --port 50051`.
3. **Establish SSH Tunnel:** `ssh -N -L 50051:127.0.0.1:50051 user@server_ip`.
4. **Start Chatting:** Run `metor -p remote_node chat` (Your local UI now securely controls the remote daemon).

### 5. Emergency & Cleanup

- `metor cleanup`: Kills zombie Tor processes (`tor.pid`) and clears stale ghost locks.
- `metor purge`: **WARNING!** Permanently wipes the entire `.metor` directory, completely destroying all databases, histories, and private keys (irreversible).

## ⚙️ Settings & Configuration

Metor can be finely tuned using the `settings` command. Values are persistently stored in `settings.json` inside your data directory.
Example: `metor settings set daemon.ephemeral_messages true`

**Important Flags:**

- `daemon.ephemeral_messages` (bool): If true, unread inbox messages are securely shredded from disk immediately upon reading.
- `daemon.require_local_auth` (bool): Requires the master password to unlock the UI even if the daemon is already running (crucial for remote SSH setups).
- `daemon.allow_drops` (bool): Globally allows or blocks the reception of asynchronous offline messages.
- `ui.chat_limit` (int): Maximum number of messages kept in the UI's volatile RAM display buffer.

## 🛡️ Security Disclaimer

While Metor leverages the Tor network for anonymity and relies on strong modern cryptography (Ed25519, Argon2i, SQLCipher), this software is provided "as-is". **Do not use this software for communication where your life or liberty depends on absolute operational security.** The codebase has not undergone a formal third-party security audit.

## 📄 License

This project is licensed under the **GNU General Public License v3.0 (GPLv3)**.
See the [LICENSE](LICENSE) file for details. Metor is free software: anyone can study, adapt, and redistribute it, ensuring the codebase remains transparent and free from proprietary surveillance.
