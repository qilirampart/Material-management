import json
import unittest
from unittest.mock import MagicMock, patch

from src.edge_cdp import edge_target_ids, evaluate_edge_page, fit_new_edge_page, set_edge_file_input


class EdgeCdpTests(unittest.TestCase):
    @patch("src.edge_cdp.websocket.create_connection")
    def test_evaluates_script_and_returns_serialized_value(self, connect):
        socket = MagicMock()
        socket.recv.return_value = json.dumps({
            "id": 1,
            "result": {"result": {"type": "object", "value": {"ok": True}}},
        })
        connect.return_value = socket

        result = evaluate_edge_page("ws://page", "({ok:true})")

        self.assertEqual(result, {"ok": True})
        payload = json.loads(socket.send.call_args.args[0])
        self.assertTrue(payload["params"]["returnByValue"])
        socket.close.assert_called_once()

    @patch("src.edge_cdp.websocket.create_connection")
    def test_sets_local_files_on_page_input(self, connect):
        socket = MagicMock()
        socket.recv.side_effect = [
            json.dumps({"id": 1, "result": {"result": {"objectId": "input-1"}}}),
            json.dumps({"id": 2, "result": {}}),
            json.dumps({"id": 3, "result": {"result": {"result": {"value": 2}}}}),
        ]
        connect.return_value = socket

        count = set_edge_file_input("ws://page", "document.querySelector('input')", ["a.mp4", "b.mp4"])

        self.assertEqual(count, 2)
        payloads = [json.loads(call.args[0]) for call in socket.send.call_args_list]
        self.assertEqual(payloads[1]["method"], "DOM.setFileInputFiles")
        self.assertEqual(payloads[1]["params"]["files"], ["a.mp4", "b.mp4"])

    @patch("src.edge_cdp.edge_targets", return_value=[{"id": "old"}, {"id": "new"}])
    def test_target_snapshot_contains_ids(self, _targets):
        self.assertEqual(edge_target_ids(), {"old", "new"})

    @patch("src.edge_cdp.websocket.create_connection")
    @patch("src.edge_cdp.edge_targets")
    def test_fits_only_the_new_platform_page(self, targets, connect):
        targets.return_value = [
            {"id": "old", "type": "page", "url": "https://market.wuread.cn/market-admin/", "webSocketDebuggerUrl": "ws://old"},
            {"id": "new", "type": "page", "url": "https://market.wuread.cn/market-admin/", "webSocketDebuggerUrl": "ws://new"},
        ]
        socket = MagicMock()
        socket.recv.return_value = json.dumps({"id": 1, "result": {}})
        connect.return_value = socket

        result = fit_new_edge_page({"old"}, "https://market.wuread.cn/market-admin/")

        self.assertEqual(result, "ws://new")
        payload = json.loads(socket.send.call_args.args[0])
        self.assertEqual(payload["method"], "Runtime.evaluate")
        self.assertIn("0.67", payload["params"]["expression"])
        socket.close.assert_called_once()

    @patch("src.edge_cdp.time.sleep")
    @patch("src.edge_cdp.websocket.create_connection")
    @patch("src.edge_cdp.edge_targets")
    def test_retries_while_debug_port_starts(self, targets, connect, sleep):
        targets.side_effect = [OSError("not ready"), [{
            "id": "new",
            "type": "page",
            "url": "https://market.wuread.cn/market-admin/",
            "webSocketDebuggerUrl": "ws://new",
        }]]
        socket = MagicMock()
        socket.recv.return_value = json.dumps({"id": 1, "result": {}})
        connect.return_value = socket

        fit_new_edge_page(set(), "https://market.wuread.cn/market-admin/")

        sleep.assert_called_once_with(0.25)


if __name__ == "__main__":
    unittest.main()
