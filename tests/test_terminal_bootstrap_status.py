"""Terminal bootstrap failure must determine the command's process status."""

import unittest
from contextlib import redirect_stderr
from io import StringIO
from unittest.mock import Mock, patch

from metor.client import FrontendLaunchContext, FrontendSelection, FrontendSelectionKind
from metor.ui.terminal.launcher import launch


class TerminalBootstrapStatusTests(unittest.TestCase):
    """Keep an unsuccessful pre-chat handshake from returning shell success."""

    def test_failed_chat_bootstrap_returns_nonzero(self) -> None:
        """The launcher reports failed authentication or initialization.

        Args:
            None
        Returns:
            None
        """
        host = Mock()
        host.initial_selection.return_value = FrontendSelection(
            FrontendSelectionKind.RESOLVED, 'fixture', 'fixture', 'fixture'
        )
        host.bootstrap.return_value.session_auth.take.return_value = None
        with patch('metor.ui.terminal.launcher.Chat') as chat_type:
            chat_type.return_value.run.return_value = False
            status = launch(FrontendLaunchContext('fixture', host))
        self.assertEqual(status, 1)
        chat_type.return_value.run.assert_called_once_with()

    def test_debug_reports_safe_prechat_phase(self) -> None:
        """Debug adds bounded timing and phase without credential contents.

        Args:
            None
        Returns:
            None
        """
        host = Mock()
        host.initial_selection.return_value = FrontendSelection(
            FrontendSelectionKind.RESOLVED, 'fixture', 'fixture', 'fixture'
        )
        host.bootstrap.return_value.session_auth.take.return_value = None
        stderr = StringIO()
        with (
            patch('metor.ui.terminal.launcher.Chat') as chat_type,
            redirect_stderr(stderr),
        ):
            chat_type.return_value.run.return_value = False
            status = launch(FrontendLaunchContext('fixture', host, debug=True))
        self.assertEqual(status, 1)
        self.assertIn('Terminal [pre-chat]: status 1; elapsed', stderr.getvalue())
