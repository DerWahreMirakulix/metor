# Metor

**Metor** is a simple, secure Tor-based messenger written in Python. It provides a persistent Tor hidden-service (onion address) along with an interactive, multiplexed chat mode. Built on a robust **Client-Daemon Architecture**, you can manage multiple secure connections simultaneously, maintain an address book, and view connection history — all from the console.

## Features

- **Client-Daemon Architecture:**
  The heavy lifting (Tor process, cryptography, connections) runs seamlessly in a background daemon. This allows you to run the chat UI, send quick messages, or manage contacts from different terminal windows simultaneously without interrupting your Tor connection.
- **Smart Contact Management & RAM Aliases:**
  Manage multiple concurrent chats flawlessly. Unknown incoming connections are assigned volatile **RAM aliases** (e.g., `abcdef1`) for the duration of the session. You can easily promote them to permanent contacts on your disk or rename them on the fly.
- **"Downgrade Delete" (Safe Removal):**
  Deleting a contact from your address book while actively chatting with them will _not_ drop the connection. Instead, the system gracefully downgrades the session back to a volatile RAM alias, keeping your chat alive and your UI fully responsive.
- **Wait Room (Asynchronous Handshake):**
  Incoming connections are placed in a background "wait room". The cryptographic handshake happens silently, and you are prompted to `/accept` or `/reject` the connection without interrupting your current chat.
- **End-to-End Reliability (ACKs):**
  Every sent message requires a cryptographic acknowledgment from the peer. Messages appear white while pending and turn green once successfully delivered. Multi-line messages are safely Base64-encoded for transit.
- **Cryptographic Authentication:**
  Connections are secured using an Ed25519 challenge-response handshake. Peers must cryptographically prove ownership of their `.onion` address before a chat is established, making identity spoofing mathematically impossible.
- **Multi-Profile Support:**
  Run multiple isolated identities from the same installation. Using the `--profile` flag, you can maintain separate `.onion` addresses, address books, Tor data directories, and chat histories without conflicts.
- **Reactive Terminal UI:**
  A robust, non-blocking command-line interface that features an intelligent buffer-draining mechanism for zero-latency input. On Unix systems, the UI automatically recalculates and redraws itself when the terminal window is resized, maintaining perfect indentation for multi-line inputs.
- **History Logging:** All events (connected, rejected, disconnected) are logged with a timestamp. View or clear logs easily via the CLI.
- **Cross-Platform Compatibility:** Metor supports both **Windows** (via Tor Expert Bundle) and **Linux** (via system package manager).

## Installation

1. **Clone the Repository:**

   ```bash
   git clone [https://github.com/DerWahreMirakulix/metor.git](https://github.com/DerWahreMirakulix/metor.git)
   ```

2. **Download and Install Tor:**
   - **Windows Users:**
     1. Download the [Tor Expert Bundle](https://www.torproject.org/download/tor/) from the official Tor Project website.
     2. Extract the bundle.
     3. Copy the `tor.exe` file **into the inner `metor` folder** (i.e., the folder containing the Python files such as `cli.py`, `chat.py`, etc.).

   - **Linux Users:** Ensure that Tor is installed on your system. You can install it using your package manager. For example:
     - **Debian/Ubuntu:**
       ```bash
       sudo apt update
       sudo apt install tor
       ```
     - **Fedora:**
       ```bash
       sudo dnf install tor
       ```
       Once installed, make sure the `tor` binary is in your PATH.

3. **Install the Package:**

   You can install the package with:

   ```bash
   pip install .
   ```

   If you’re developing or wish to install it in editable mode, run:

   ```bash
   pip install -e .
   ```

   Make sure you run those commands inside the root directory of the repository.

## Usage

After installation, the command `metor` will be available in your console.

### 1. Start the Background Daemon

Before chatting, you need to start the Tor engine and connection handler:

```bash
metor daemon
```

### 2. Global Options

Keep different identities completely separated by using profiles.

- `-p, --profile <name>`: Set the active profile (default: 'default'). Keeps history, onion addresses, contacts, and locks isolated.

### 3. Core & Identity Commands

Open a second terminal window to interact with your running daemon:

- `metor help` – Show the help overview.
- `metor chat` – Enter the interactive multi-chat UI.
- `metor cleanup` – Kill zombie Tor processes and clear broken locks.
- `metor address [show|generate]` – View or cycle your hidden service address.
- `metor profiles [list|add|rm|rename]` – Manage isolated profile environments.
- `metor history [clear]` – View or wipe the connection event log.

### 4. External Contact Management

You can manage your address book from outside the chat using these CLI commands:

- `metor contacts list` – List all contacts in your address book.
- `metor contacts add <alias> [onion]` – Add a manual contact or save a running RAM alias to disk.
- `metor contacts rm <alias>` – Delete a contact (active sessions safely downgrade to RAM).
- `metor contacts rename <old> <new>` – Rename a saved contact or active session.

### 5. In-Chat Commands

Once inside the `metor chat` interface, you can manage your active sessions directly:

- The `[alias]` or `[old]` parameter can be safely omitted for the commands above if you are currently focused on a peer. The system will automatically target your focused chat.

- Any other text entered is sent as a chat message to the currently focused peer. Use `Ctrl+N` or `Alt+Enter` for multi-line messages.

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
