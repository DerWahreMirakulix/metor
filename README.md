# Metor

**Metor** is a simple, secure Tor-based messenger written in Python. It provides a persistent Tor hidden-service (onion address) along with an interactive, multiplexed chat mode and asynchronous offline messaging. Built on a robust **Client-Daemon Architecture** and structured via **Domain-Driven Design**, you can manage multiple secure connections simultaneously, maintain an address book, queue offline messages, and view connection history — all from the console.

## Features

- **Client-Daemon Architecture:**
  The heavy lifting (Tor process, cryptography, connections, and outbox routing) runs seamlessly in a background daemon. This allows you to run the chat UI, send quick asynchronous messages, or manage contacts from different terminal windows simultaneously without interrupting your Tor connection.
- **Stateless UI (Remote Support):**
  Because the daemon processes are decoupled from the UI, you can run the daemon 24/7 on a remote VPS and securely connect your local laptop UI to it via an SSH tunnel.
- **Asynchronous Offline Messaging (Drops):**
  Send messages even when your contact is offline. The Daemon queues your messages in a local SQLite Outbox and automatically negotiates delivery in the background as soon as the peer comes online. Unread messages are safely stored in your Inbox.
- **Strongly-Typed IPC API:**
  Communication between the background daemon and the chat UI is handled via a strict, Data Transfer Object (DTO) based IPC API, ensuring zero data loss and maximum stability.
- **Smart Contact Management & Discovered Peers:**
  Manage multiple concurrent chats flawlessly. Unknown incoming connections are assigned volatile **Discovered Peer** aliases (e.g., `exw4kj1`) dynamically. You can easily promote them to permanent contacts on your disk or rename them on the fly.
- **"Downgrade Delete" (Safe Removal):**
  Deleting a contact from your address book while actively chatting with them will _not_ drop the connection. Instead, the system gracefully downgrades the session back to a volatile alias, keeping your chat alive and your UI fully responsive.
- **End-to-End Reliability & Cryptographic Authentication:**
  Every sent message requires a cryptographic acknowledgment. Connections are secured using an Ed25519 challenge-response handshake. Peers must cryptographically prove ownership of their `.onion` address before a chat is established, making identity spoofing mathematically impossible.
- **System-Wide Local SQLite Storage & Multi-Profile Support:**
  Run multiple isolated identities from the same installation safely stored in your system's data directory. Using the `-p` flag, you can maintain separate `.onion` addresses, Tor data directories, and SQLite-backed chat histories, address books, and message queues without conflicts.
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

### 3. Advanced Setup: Remote Daemon (24/7 Node)

You can run your Metor daemon 24/7 on a secure server (VPS) and connect to it from your local laptop. The connection is secured natively using an SSH tunnel.

**Step 1: On your Server (VPS)**
Create a profile and assign a static port for the local IPC server:

```bash
metor profiles add my_server --port 50051
metor -p my_server daemon
```

**Step 2: On your Laptop**
Create a corresponding remote profile pointing to that same port:

```bash
metor profiles add remote_node --remote --port 50051
```

**Step 3: Connect via SSH Tunnel**
Before using Metor on your laptop, establish a secure SSH tunnel forwarding the local port to your server:

```bash
ssh -N -L 50051:127.0.0.1:50051 user@your_server_ip
```

Now, simply run `metor -p remote_node chat` (or any other command) on your laptop. The UI will seamlessly and securely communicate with your remote daemon.

### 4. Core Commands & Maintenance

Open a second terminal window to interact with your running daemon:

- `metor help` – Show the help overview.
- `metor chat` – Enter the interactive multiplexed chat UI.
- `metor cleanup` – Kill zombie Tor processes and clear broken locks.
- `metor purge` – **WARNING:** Permanently wipe ALL profiles, keys, databases, and message history.

### 5. Asynchronous Messaging (Headless)

Send and receive messages directly from the command line without entering the chat UI:

- `metor send <alias> "msg"` – Drop an offline message to a contact.
- `metor inbox` – Check for unread offline messages.
- `metor read <alias>` – Read and clear unread messages from an alias.
- `metor messages [show] <alias> [limit]` – View past chat history with a contact.
- `metor messages clear [alias]` – Delete message history.

### 6. Profile & Identity Management

- `metor address [show|generate]` – View or cycle your hidden service address.
- `metor profiles [list|add|rm]` – List, create, or remove isolated profiles.
- `metor profiles [rename|set-default|clear]` – Manage existing profile configurations.
- `metor profiles add <name> [--remote] [--port <int>]` – Create a new profile (local or remote via SSH).
- `metor history [show|clear] [alias]` – View or wipe the connection event log.

### 7. External Contact Management

You can manage your address book from outside the chat using these CLI commands:

- `metor contacts [list]` – List all contacts in your address book.
- `metor contacts add <alias> [onion]` – Add a manual contact or save a running RAM alias.
- `metor contacts rm <alias>` – Delete contact (active sessions revert to RAM).
- `metor contacts rename <old> <new>` – Rename a saved contact or active session.
- `metor contacts clear` – Wipe the address book completely.

### 8. In-Chat Commands

Once inside the `metor chat` interface, you can manage your active sessions directly.
_Note: The `[alias]` or `[old]` parameter can be safely omitted for the commands below if you are currently focused on a peer._

**Session Management:**

- `/connect <onion|alias>` – Establish a new secure connection.
- `/accept [alias]` – Accept a background connection request.
- `/reject [alias]` – Reject a background connection request.
- `/switch [..|<onion|alias>]` – Switch focus (use `..` to remove focus).
- `/end [alias]` – Terminate an active or pending connection.
- `/sessions` – List all active and pending sessions.
- `/clear` – Wipe the current chat display.
- `/exit` – Close the UI (Daemon stays active).

**In-Chat Address Book Management:**

- `/contacts list` – Show saved contacts and temporary RAM aliases.
- `/contacts add [alias] [onion]` – Save a RAM alias or add a new manual contact.
- `/contacts rm [alias]` – Remove from disk (active chat reverts to RAM).
- `/contacts rename [old] <new>` – Change the name of any RAM or Disk alias.

## Security Disclaimer

While Metor utilizes the Tor network for anonymity and encryption, this software is provided as-is, without any guarantees. Do not use this software for highly sensitive communication where your life or liberty depends on absolute operational security. The codebase has not undergone a formal third-party security audit.

## License

This project is licensed under the GNU General Public License v3.0 (GPLv3).
See the [LICENSE](LICENSE) file for details.

Metor is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later version. This ensures that Metor and any derivative works remain open, transparent, and free from proprietary surveillance.
