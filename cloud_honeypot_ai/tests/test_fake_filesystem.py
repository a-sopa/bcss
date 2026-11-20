"""Unit tests for virtual filesystem and canary honey-tokens."""

import unittest

from cloud_honeypot_ai.config import CONFIG
from cloud_honeypot_ai.core.fake_filesystem import FakeFilesystem


class TestFakeFilesystem(unittest.TestCase):

    def setUp(self):
        self.fs = FakeFilesystem()

    def test_default_system_files(self):
        self.assertTrue(self.fs.exists("/etc/passwd"))
        self.assertTrue(self.fs.exists("/etc/shadow"))
        self.assertTrue(self.fs.exists("/etc/os-release"))

        content, canary = self.fs.read_file("/etc/passwd")
        self.assertIsNotNone(content)
        self.assertIn("root:x:0:0", content)
        self.assertIsNone(canary)

    def test_canary_honey_tokens(self):
        # /etc/shadow should trigger canary
        _, canary_shadow = self.fs.read_file("/etc/shadow")
        self.assertEqual(canary_shadow, "HONEY_SHADOW_EXFILTRATION")

        # AWS credentials should trigger canary
        aws_content, canary_aws = self.fs.read_file("/home/ubuntu/.aws/credentials")
        self.assertIn(CONFIG.canary_aws_key_id, aws_content)
        self.assertEqual(canary_aws, "CANARY_AWS_CREDENTIAL_STOLEN")

        # .env should trigger canary
        env_content, canary_env = self.fs.read_file("/app/.env")
        self.assertIn("DATABASE_URL", env_content)
        self.assertEqual(canary_env, "CANARY_ENV_FILE_LEAK")

    def test_path_normalization(self):
        # Relative path resolution
        self.assertEqual(self.fs._normalize_path("passwd", "/etc"), "/etc/passwd")
        self.assertEqual(self.fs._normalize_path("../../etc/passwd", "/home/ubuntu"), "/etc/passwd")
        self.assertEqual(self.fs._normalize_path("./foo/bar", "/tmp"), "/tmp/foo/bar")

    def test_dir_listing(self):
        files = self.fs.list_dir("/etc")
        names = [f.name for f in files]
        self.assertIn("passwd", names)
        self.assertIn("shadow", names)
        self.assertIn("hosts", names)

    def test_write_and_read_new_file(self):
        success = self.fs.write_file("/tmp/malware.sh", "#!/bin/sh\necho test\n", owner="ubuntu")
        self.assertTrue(success)
        self.assertTrue(self.fs.exists("/tmp/malware.sh"))

        content, _ = self.fs.read_file("/tmp/malware.sh")
        self.assertEqual(content, "#!/bin/sh\necho test\n")


if __name__ == "__main__":
    unittest.main()
