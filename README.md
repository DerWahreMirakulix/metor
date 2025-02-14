# Metor

**Metor** is a simple Tor-based messenger written in Python. It provides a persistent Tor hidden-service (onion address) along with an interactive chat mode. You can run a listener, connect to remote peers (optionally anonymously), and view connection history — all from the console.

## Features

- **Persistent Onion Address:**  
  Generate and view your current onion address with:

  - `metor address show`
  - `metor address generate` (only when no chat session is active)

- **Chat Mode:**  
  Start chat mode with:

  - `metor chat`

  While in chat mode you can use the following commands at the `metor>` prompt:

  - `/connect [onion] [--anonymous/-a]` – Connect to a remote peer (self‑connections are disallowed).
  - `/end` – End the current connection (both peers see a disconnect message).
  - `/clear` – Clear the chat display (the initial help text and connection status remain visible).
  - `/exit` – Exit chat mode (disconnecting first if needed).

  If an incoming connection is received while a chat is active, it is automatically rejected with an appropriate message.

- **History Logging:**  
  All events (incoming/outgoing, connected, rejected, disconnected) are logged with a timestamp. You can view the log with:

  - `metor history`

  And clear it with:

  - `metor history clear`

- **Cross-Platform Compatibility:**  
  Metor supports both **Windows** and **Linux/Mac**:
  - **Windows:** You must manually download the Tor Expert Bundle.
  - **Linux/Mac:** The system-installed `tor` binary is used.

## Installation

1. **Clone the Repository:**

   ```bash
   git clone https://github.com/DerWahreMirakulix/metor
   ```

2. **Download and Install Tor:**

   - **Windows Users:**

     1. Download the [Tor Expert Bundle](https://www.torproject.org/download/tor/) from the official Tor Project website.
     2. Extract the bundle.
     3. Copy the `tor.exe` file **into the inner `metor` folder** (i.e. the folder containing the Python files such as `cli.py`, `core.py`, etc.).

   - **Linux/Mac Users:**  
     Ensure that Tor is installed on your system. You can install it using your package manager. For example:

     - **Debian/Ubuntu:**

       ```bash
       sudo apt update
       sudo apt install tor
       ```

     - **Fedora:**

       ```bash
       sudo dnf install tor
       ```

     - **macOS (using Homebrew):**
       ```bash
       brew install tor
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

   Make sure you run those commands inside root directory of the repository.

## Usage

After installation, the command `metor` will be available in your console.

- **Show Help:**

  ```bash
  metor help
  ```

  This displays all top-level commands as well as in-chat commands.

- **Start Chat Mode:**

  ```bash
  metor chat
  ```

  Once in chat mode, you will see a prompt (`metor>`). The available in-chat commands are:

  - `/connect [onion] [--anonymous/-a]` – Connect to a remote peer.
  - `/end` – Disconnect the current chat.
  - `/clear` – Clear the chat display.
  - `/exit` – Exit chat mode.

- **Manage Your Onion Address:**

  ```bash
  metor address show        # Show the current onion address.
  metor address generate    # Generate a new onion address (only if no chat is active).
  ```

- **View/Clear Connection History:**
  ```bash
  metor history             # Show connection history.
  metor history clear       # Clear connection history.
  ```

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.
