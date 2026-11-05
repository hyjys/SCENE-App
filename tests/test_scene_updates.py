"""Network-free updater tests; no installer is launched by these tests."""

from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

import scene_updates as updates


INSTALLER = b"MZ" + bytes(range(256)) * 20


class Response(io.BytesIO):
    def __init__(self, value, length=None):
        super().__init__(value)
        self.headers = {} if length is None else {"Content-Length": str(length)}


def release(version="0.5", *, legacy=False, digest=True):
    tag = "v" + version
    name = f"sceneapp-{version}-windows-x64" + ("-setup" if legacy else "") + ".exe"
    return updates.ReleaseUpdate(version, tag, name,
                                 f"{updates.RELEASES_URL}/download/{tag}/{name}", len(INSTALLER),
                                 hashlib.sha256(INSTALLER).hexdigest() if digest else None,
                                 f"{updates.RELEASES_URL}/tag/{tag}", "New release")


def metadata(update=None):
    update = update or release()
    return {"tag_name": update.tag, "html_url": update.release_url, "draft": False,
            "prerelease": False, "body": update.notes,
            "assets": [{"name": update.name, "browser_download_url": update.url,
                        "size": update.size, "digest": f"sha256:{update.sha256}" if update.sha256 else None,
                        "state": "uploaded"}]}


class UpdateCheckTests(unittest.TestCase):
    def check(self, data, current="0.4"):
        with patch.object(updates, "_open", return_value=Response(json.dumps(data).encode())) as request:
            result = updates.check_for_update(current)
        request.assert_called_once_with(updates.LATEST_API)
        return result

    def test_numeric_versions_and_zero_patch(self):
        self.assertGreater(updates.version_tuple("0.10"), updates.version_tuple("0.9"))
        self.assertEqual(updates.version_tuple("v0.4"), updates.version_tuple("0.4.0"))
        for invalid in ("0.4rc1", "../0.4", "0.4\n", "v0.4-beta", "0.4+build", "0.4.0.0.1"):
            with self.subTest(invalid=invalid), self.assertRaises(updates.UpdateError):
                updates.version_tuple(invalid)

    def test_latest_stable_installer_and_digest(self):
        self.assertEqual(self.check(metadata()), release())

    def test_current_and_older_are_not_offered(self):
        self.assertIsNone(self.check(metadata(release("0.4.0"))))
        self.assertIsNone(self.check(metadata(release("0.3"))))

    def test_drafts_prereleases_and_rc_tags_are_ignored(self):
        for field in ("draft", "prerelease"):
            data = metadata()
            data[field] = True
            self.assertIsNone(self.check(data))
        data = metadata()
        data["tag_name"] = "v0.5-rc1"
        self.assertIsNone(self.check(data))

    def test_requested_name_preferred_over_existing_legacy_setup_name(self):
        data = metadata(release(legacy=True))
        data["assets"] += metadata()["assets"]
        self.assertEqual(self.check(data).name, release().name)
        self.assertEqual(self.check(metadata(release(legacy=True))), release(legacy=True))

    def test_newer_release_without_installer_reports_upload_in_progress(self):
        data = metadata()
        data["assets"] = []
        with self.assertRaisesRegex(updates.UpdateError, "설치 파일이 아직 없습니다"):
            self.check(data)

    def test_url_cannot_leave_the_exact_repo_and_tag(self):
        for url in ("https://evil.example/sceneapp-0.5-windows-x64.exe",
                    release().url.replace("hyjys", "other"),
                    release().url.replace("v0.5/", "v0.6/"),
                    release().url.replace("https:", "http:"),
                    release().url + "?redirect=1"):
            data = metadata()
            data["assets"][0]["browser_download_url"] = url
            with self.subTest(url=url), self.assertRaises(updates.UpdateError):
                self.check(data)

    def test_rate_limit_and_empty_releases(self):
        with patch.object(updates, "_open", side_effect=urllib.error.HTTPError(updates.LATEST_API, 403, "rate", {}, None)):
            with self.assertRaisesRegex(updates.UpdateError, "요청 한도"):
                updates.check_for_update("0.4")
        with patch.object(updates, "_open", side_effect=urllib.error.HTTPError(updates.LATEST_API, 404, "missing", {}, None)):
            self.assertIsNone(updates.check_for_update("0.4"))

    def test_metadata_size_digest_and_asset_size_validation(self):
        for field, invalid in (("size", -1), ("size", True), ("digest", "sha256:no"),
                               ("digest", "sha512:abc")):
            data = metadata()
            data["assets"][0][field] = invalid
            with self.subTest(field=field, invalid=invalid), self.assertRaises(updates.UpdateError):
                self.check(data)
        with patch.object(updates, "_open", return_value=Response(b" " * (updates.MAX_METADATA_BYTES + 1))):
            with self.assertRaisesRegex(updates.UpdateError, "너무 큽니다"):
                updates.check_for_update("0.4")

    def test_redirect_rejects_http_credentials_and_other_hosts(self):
        handler = updates._GitHubRedirects()
        req = urllib.request.Request(release().url)
        for destination in ("http://github.com/download", "https://github.com.evil.example/download",
                            "https://github.com@evil.example/download", "https://evil.example/exe"):
            with self.subTest(destination=destination), self.assertRaises(updates.UpdateError):
                handler.redirect_request(req, None, 302, "Found", {}, destination)


class UpdateDownloadTests(unittest.TestCase):
    def test_atomic_success_with_digest_and_progress(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            progress = []
            with patch.object(updates, "_open", return_value=Response(INSTALLER, len(INSTALLER))):
                output = updates.download_update(release(), cache_dir=directory,
                                                 progress=lambda current, total: progress.append((current, total)))
            self.assertEqual(output, directory / release().name)
            self.assertEqual(output.read_bytes(), INSTALLER)
            self.assertEqual(progress[0], (0, len(INSTALLER)))
            self.assertEqual(progress[-1], (len(INSTALLER), len(INSTALLER)))
            self.assertEqual(list(directory.glob("*.part")), [])

    def test_truncated_bad_hash_and_html_do_not_replace_previous_installer(self):
        for data, expected in ((INSTALLER[:-1], "완전하지"),
                               (b"MZ" + b"x" * (len(INSTALLER) - 2), "SHA-256"),
                               (b"<html>" + b"x" * (len(INSTALLER) - 6), "실행 파일")):
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as folder:
                directory = Path(folder)
                existing = directory / release().name
                existing.write_bytes(b"previous installer")
                with patch.object(updates, "_open", return_value=Response(data)):
                    with self.assertRaisesRegex(updates.UpdateError, expected):
                        updates.download_update(release(), cache_dir=directory)
                self.assertEqual(existing.read_bytes(), b"previous installer")
                self.assertEqual(list(directory.glob("*.part")), [])

    def test_cancel_before_and_during_download_cleans_partials(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            event = threading.Event()
            event.set()
            with patch.object(updates, "_open") as request:
                with self.assertRaises(updates.UpdateCancelled):
                    updates.download_update(release(), cache_dir=directory, cancel=event)
                request.assert_not_called()
            event.clear()
            with patch.object(updates, "_open", return_value=Response(INSTALLER)):
                with self.assertRaises(updates.UpdateCancelled):
                    updates.download_update(release(), cache_dir=directory, cancel=event,
                                            progress=lambda current, total: event.set() if current else None)
            self.assertEqual(list(directory.iterdir()), [])

    def test_server_size_mismatch_or_excess_rejected(self):
        for data, header in ((INSTALLER, len(INSTALLER) + 1), (INSTALLER + b"x", None)):
            with tempfile.TemporaryDirectory() as folder:
                with patch.object(updates, "_open", return_value=Response(data, header)):
                    with self.assertRaises(updates.UpdateError):
                        updates.download_update(release(), cache_dir=Path(folder))
                self.assertEqual(list(Path(folder).iterdir()), [])

    def test_invalid_update_never_uses_network(self):
        with patch.object(updates, "_open") as request:
            with self.assertRaises(updates.UpdateError):
                updates.download_update(replace(release(), url="https://evil.example/exe"))
            request.assert_not_called()

    def test_missing_optional_github_digest_still_checks_size_and_exe(self):
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(updates, "_open", return_value=Response(INSTALLER)):
                output = updates.download_update(release(digest=False), cache_dir=Path(folder))
            self.assertEqual(output.read_bytes(), INSTALLER)

    def test_installer_launch_uses_argument_list_interactive_wizard(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / release().name
            path.write_bytes(INSTALLER)
            with patch.object(updates.sys, "platform", "win32"), patch.object(updates.subprocess, "Popen") as launch:
                updates.launch_installer(path)
            args = launch.call_args.args[0]
            self.assertEqual(args[0], str(path.resolve()))
            self.assertIn("/NORESTART", args)
            self.assertIn("/CLOSEAPPLICATIONS", args)
            self.assertNotIn("/VERYSILENT", args)
            self.assertFalse(launch.call_args.kwargs.get("shell", False))


if __name__ == "__main__":
    unittest.main()
