# Metor

**Metor** is a simple, secure Tor-based messenger written in Python. It provides a persistent Tor hidden-service (onion address) along with an interactive, multiplexed chat mode. Built on a robust **Client-Daemon Architecture**, you can manage multiple secure connections simultaneously, maintain an address book, and view connection history — all from the console.

## Features

- **Client-Daemon Architecture:**
  The heavy lifting (Tor process, cryptography, connections) runs seamlessly in a background daemon. This allows you to run the chat UI, send quick messages, or manage contacts from different terminal windows simultaneously without interrupting your Tor connection.
- **Multi-Chat & Address Book:**
  Manage multiple concurrent chats. Metor automatically assigns short aliases to new peers, allowing you to easily switch focus between conversations. Contacts can be seamlessly managed and renamed both inside the chat and via the CLI.
- **Wait Room (Asynchronous Handshake):**
  Incoming connections are placed in a background "wait room". The cryptographic handshake happens silently, and you are prompted to `/accept` or `/reject` the connection without interrupting your current chat.
- **End-to-End Reliability (ACKs):**
  Every sent message requires a cryptographic acknowledgment from the peer. Messages appear white while pending and turn green once successfully delivered. Multi-line messages are safely Base64-encoded for transit.
- **Cryptographic Authentication:**
  Connections are secured using an Ed25519 challenge-response handshake. Peers must cryptographically prove ownership of their `.onion` address before a chat is established, making identity spoofing mathematically impossible.
- **Multi-Profile Support:**
  Run multiple isolated identities from the same installation. Using the `--profile` flag, you can maintain separate `.onion` addresses, address books, Tor data directories, and chat histories without conflicts.
- **Reactive Terminal UI:**
  A robust, non-blocking command-line interface that clearly separates static system snapshots (`system>`) from dynamic chat events (`info>`). On Unix systems, the UI automatically recalculates and redraws itself when the terminal window is resized, maintaining perfect indentation for multi-line inputs.
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

### 3. CLI Commands

Open a second terminal window to interact with your running daemon:

- `metor help` – Show all commands.
- `metor chat` – Start the interactive chat mode UI.
- `metor address show` – Show the current onion address.
- `metor address generate` – Generate a new onion address (if no daemon is running).
- `metor history [clear]` – Show or clear connection history.
- `metor contacts [list|add|rm|rename] [..options]` – Manage your address book externally.
- `metor profiles [list|add|rm|rename|set-default] [..options]` – Manage your isolated profiles.
- `metor cleanup` – Emergency tool: Kill zombie Tor processes and clear broken locks.

### 4. In-Chat Commands

Once inside the `metor chat` interface, you can manage your active sessions directly:

- `/connect [onion/alias]` – Connect to a remote peer.
- `/accept [alias]` – Accept an incoming connection request.
- `/reject [alias]` – Reject an incoming connection request.
- `/switch [..|alias]` – Switch your input focus to another active chat (use `..` to remove focus).
- `/contacts [list|add|rm|rename] [..options]` – Manage your address book directly inside the active chat.
- `/connections` – Show all active and pending connections.
- `/end [alias]` – Disconnect the currently focused chat, or specify an alias to end a background chat.
- `/clear` – Clear the terminal display.
- `/exit` – Close the UI (the background daemon keeps running).

_(Any other text entered is sent as a chat message to the currently focused peer. Use `Ctrl+N` or `Alt+Enter` for multi-line messages)._

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
