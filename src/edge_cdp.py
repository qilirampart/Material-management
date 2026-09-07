from __future__ import annotations

import json
import time
import urllib.request

import websocket


def edge_targets(port: int = 9222) -> list[dict]:
    with urllib.request.urlopen(f"http://127.0.0.1:{int(port)}/json/list", timeout=2) as response:
        return json.load(response)


def edge_target_ids(port: int = 9222) -> set[str]:
    return {str(item.get("id")) for item in edge_targets(port) if item.get("id")}


def fit_new_edge_page(
    previous_ids: set[str],
    url_prefix: str,
    port: int = 9222,
    zoom: float = 0.67,
) -> str:
    target = None
    for _ in range(12):
        try:
            targets = edge_targets(port)
        except OSError:
            time.sleep(0.25)
            continue
        target = next(
            (
                item
                for item in targets
                if str(item.get("id")) not in previous_ids
                and item.get("type") == "page"
                and str(item.get("url", "")).startswith(url_prefix)
            ),
            None,
        )
        if target:
            break
        time.sleep(0.25)
    if not target or not target.get("webSocketDebuggerUrl"):
        raise RuntimeError("尚未找到新打开的 Edge 平台页面。")
    zoom_text = f"{float(zoom):.2f}"
    expression = (
        f"document.documentElement.style.zoom='{zoom_text}';"
        "for(const frame of document.querySelectorAll('iframe')){"
        f"try{{frame.contentDocument.documentElement.style.zoom='{zoom_text}'}}catch(_){{}}}}"
    )
    socket = websocket.create_connection(
        target["webSocketDebuggerUrl"], timeout=3, suppress_origin=True
    )
    try:
        socket.send(json.dumps({
            "id": 1,
            "method": "Runtime.evaluate",
            "params": {"expression": expression},
        }))
        response = json.loads(socket.recv())
        if response.get("error"):
            raise RuntimeError(response["error"].get("message", "Edge 页面缩放失败。"))
    finally:
        socket.close()
    return str(target["webSocketDebuggerUrl"])
