# Metor

**Metor** is a simple, secure Tor-based messenger written in Python. It provides a persistent Tor hidden-service (onion address) along with an interactive, multiplexed chat mode. Built on a robust **Client-Daemon Architecture** and structured via **Domain-Driven Design**, you can manage multiple secure connections simultaneously, maintain an address book, and view connection history — all from the console.

## Features

- **Client-Daemon Architecture:**
  The heavy lifting (Tor process, cryptography, connections) runs seamlessly in a background daemon. This allows you to run the chat UI, send quick messages, or manage contacts from different terminal windows simultaneously without interrupting your Tor connection.
- **Strongly-Typed IPC API:**
  Communication between the background daemon and the chat UI is handled via a strict, Data Transfer Object (DTO) based IPC API, ensuring zero data loss and maximum stability.
- **Smart Contact Management & RAM Aliases:**
  Manage multiple concurrent chats flawlessly. Unknown incoming connections are assigned volatile **RAM aliases** (e.g., `abcdef1`) for the duration of the session. You can easily promote them to permanent contacts on your disk or rename them on the fly.
- **"Downgrade Delete" (Safe Removal):**
  Deleting a contact from your address book while actively chatting with them will _not_ drop the connection. Instead, the system gracefully downgrades the session back to a volatile RAM alias, keeping your chat alive and your UI fully responsive.
- **Wait Room (Asynchronous Handshake):**
  Incoming connections are placed in a background "wait room". The cryptographic handshake happens silently, and you are prompted to `/accept` or `/reject` the connection without interrupting your current chat.
- **End-to-End Reliability & Cryptographic Authentication:**
  Every sent message requires a cryptographic acknowledgment. Connections are secured using an Ed25519 challenge-response handshake. Peers must cryptographically prove ownership of their `.onion` address before a chat is established, making identity spoofing mathematically impossible.
- **System-Wide Local SQLite Storage & Multi-Profile Support:**
  Run multiple isolated identities from the same installation safely stored in your system's home directory. Using the `--profile` flag, you can maintain separate `.onion` addresses, Tor data directories, and SQLite-backed chat histories without conflicts.
- **Reactive Terminal UI:**
  A robust, non-blocking command-line interface. On Unix systems, the UI automatically recalculates and redraws itself when the terminal window is resized, maintaining perfect indentation for multi-line inputs.

## Installation

For security reasons and to prevent supply-chain attacks, Metor **does not** bundle the Tor binary. You must download it directly from the official Tor Project.

### 1. Clone the Repository

Clone the project to your local machine:

```bash
git clone https://github.com/DerWahreMirakulix/metor.git
```

Enter the repository:

```bash
cd metor
```

### 2. Download and Install Tor

Depending on your operating system, you need to provide the Tor binary:

**For Windows Users (Manual Security Install):**

1. Download the [Tor Expert Bundle](https://www.torproject.org/download/tor/) directly from the official Tor Project website.
2. Extract the downloaded archive.
3. Go to your system's user home directory (e.g., `C:\Users\YourUsername\`).
4. Create a folder named `.metor`.
5. Copy the extracted `tor.exe` file directly into this new folder.
   _(The exact path MUST be: `C:\Users\YourUsername\.metor\tor.exe`)_

**For Linux Users (Package Manager):**
Ensure that Tor is installed on your system globally via your package manager:

- **Debian/Ubuntu:** `sudo apt update && sudo apt install tor`
- **Fedora:** `sudo dnf install tor`

### 3. Install the Package

Once the Tor binary is in place (or installed globally on Linux), install the Python package. Make sure you run these commands from the root directory of the repository (where the `setup.py` is located).

For a standard installation, run:

```bash
pip install .
```

If you’re developing, contributing, or wish to install it in editable mode (so code changes apply immediately without reinstalling), run:

```bash
pip install -e .
```

## Usage

After installation, the global command `metor` will be available anywhere in your console. All configuration, keys, and databases will be safely stored in your `~/.metor/` directory.

### 1. Start the Background Daemon

Before chatting, you need to start the Tor engine, generate your keys, and spin up the IPC handler. Leave this running in a terminal:

```bash
metor daemon
```

### 2. Global Options

Keep different identities completely separated by using profiles.

- `-p, --profile <name>`: Set the active profile (default: 'default'). Keeps history, onion addresses, contacts, and locks isolated.

### 3. Core & Identity Commands

Open a second terminal window to interact with your running daemon:

- `metor help` – Show the help overview.
- `metor chat` – Enter the interactive multiplexed chat UI.
- `metor cleanup` – Kill zombie Tor processes and clear broken locks.
- `metor address [show|generate]` – View or cycle your hidden service address.
- `metor profiles [list|add|rm|rename|set-default]` – Manage isolated profile environments.
- `metor history [clear]` – View or wipe the SQLite connection event log.

### 4. External Contact Management

You can manage your address book from outside the chat using these CLI commands:

- `metor contacts list` – List all contacts in your address book.
- `metor contacts add <alias> [onion]` – Add a manual contact or save a running RAM alias to disk.
- `metor contacts rm <alias>` – Delete a contact (active sessions safely downgrade to RAM).
- `metor contacts rename <old> <new>` – Rename a saved contact or active session.

### 5. In-Chat Commands

Once inside the `metor chat` interface, you can manage your active sessions directly.
_Note: The `[alias]` or `[old]` parameter can be safely omitted for the commands below if you are currently focused on a peer._

**Session Management:**

- `/connect <onion|alias>` – Establish a new secure connection.
- `/accept [alias]` – Accept a background connection request.
- `/reject [alias]` – Reject a background connection request.
- `/switch [..|alias]` – Switch focus (use `..` to remove focus).
- `/end [alias]` – Terminate an active or pending connection.
- `/connections` – List all active and pending sessions.
- `/clear` – Wipe the current chat display.
- `/exit` – Close the UI (Daemon stays active).

**In-Chat Address Book Management:**

- `/contacts list` – Show saved contacts and temporary RAM aliases.
- `/contacts add [alias] [onion]` – Save a RAM alias or add a new manual contact.
- `/contacts rm [alias]` – Remove from disk (active chat reverts to RAM).
- `/contacts rename [old] <new>` – Change the name of any RAM or Disk alias.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
