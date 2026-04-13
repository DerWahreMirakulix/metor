"""Regression tests for chat disconnect exit behavior."""

# ruff: noqa: E402

import sys
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from metor.data.profile import ProfileManager
from metor.ui import Theme
from metor.ui.chat.engine import Chat
from metor.ui.chat.models import ChatMessageType


class _DummyConfig:
    def get_float(self, _key: object) -> float:
        return 0.1


class _DummyProfileManager:
    def __init__(self) -> None:
        self.config: _DummyConfig = _DummyConfig()

    def get_daemon_port(self) -> int:
        return 43111


class ChatContractTests(unittest.TestCase):
    @staticmethod
    def _build_chat(renderer: Mock) -> Chat:
        with (
            patch('metor.ui.chat.engine.Renderer', return_value=renderer),
            patch('metor.ui.chat.engine.IpcClient'),
            patch('metor.ui.chat.engine.EventHandler'),
            patch('metor.ui.chat.engine.CommandDispatcher'),
        ):
            return Chat(cast(ProfileManager, _DummyProfileManager()))

    def test_disconnect_exit_message_skips_prompt_during_chat_loop(self) -> None:
        renderer = Mock()
        ipc_client = Mock()
        ipc_client.connect.return_value = True
        chat = self._build_chat(renderer)

        def trigger_disconnect(_stop_event: object) -> None:
            chat._disconnect_event.set()
            return None

        renderer.read_line.side_effect = trigger_disconnect

        with (
            patch('metor.ui.chat.engine.IpcClient', return_value=ipc_client),
            patch('metor.ui.chat.engine.EventHandler'),
            patch('metor.ui.chat.engine.CommandDispatcher'),
            patch.object(Chat, '_bootstrap_ipc_session', return_value=True),
            patch.object(Chat, '_print_header'),
            patch.object(Chat, '_shutdown'),
        ):
            chat.run()

        renderer.clear_input_area.assert_called()
        renderer.print_divider.assert_called_once_with(skip_prompt=True)
        renderer.print_message.assert_any_call(
            f'{Theme.RED}Connection to Daemon lost! Exiting...{Theme.RESET}',
            msg_type=ChatMessageType.RAW,
            skip_prompt=True,
        )

    def test_disconnect_during_bootstrap_skips_prompt(self) -> None:
        renderer = Mock()
        chat = self._build_chat(renderer)
        chat._ipc = Mock()
        chat._disconnect_event.set()

        result = chat._bootstrap_ipc_session()

        self.assertFalse(result)
        renderer.clear_input_area.assert_called_once()
        renderer.print_divider.assert_not_called()
        renderer.print_message.assert_called_once_with(
            f'{Theme.RED}Connection to Daemon lost! Exiting...{Theme.RESET}',
            msg_type=ChatMessageType.RAW,
            skip_prompt=True,
        )


if __name__ == '__main__':
    unittest.main()
