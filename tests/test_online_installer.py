import unittest

from src.online_installer import latest_release, release_asset


class Response:
    def __init__(self, url): self.url = url
    def geturl(self): return self.url
    def __enter__(self): return self
    def __exit__(self, *args): return False


class OnlineInstallerTests(unittest.TestCase):
    def test_release_asset_uses_stable_windows_name(self):
        name, url = release_asset("Windows", "0.3.8")
        self.assertEqual(name, "DianzhongMaterialAssistant-Setup-0.3.8.exe")
        self.assertTrue(url.endswith("/v0.3.8/DianzhongMaterialAssistant-Setup-0.3.8.exe"))

    def test_latest_release_reads_github_redirect_tag(self):
        response = Response("https://github.com/qilirampart/Material-management/releases/tag/v0.3.8")
        version, page = latest_release(lambda request, timeout: response)
        self.assertEqual(version, "0.3.8")
        self.assertEqual(page, response.url)
