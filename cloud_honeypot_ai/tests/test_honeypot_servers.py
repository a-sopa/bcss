"""Unit tests for network honeypot servers (TCP, HTTP, SSH)."""

import socket
import time
import unittest
import urllib.request

from cloud_honeypot_ai.core.http_honeypot import HTTPHoneypotServer
from cloud_honeypot_ai.core.session import SessionManager
from cloud_honeypot_ai.core.ssh_honeypot import SSHHoneypotServer
from cloud_honeypot_ai.core.tcp_honeypot import TCPHoneypotServer


class TestHoneypotServers(unittest.TestCase):

    def setUp(self):
        self.session_mgr = SessionManager()

    def test_tcp_honeypot_interaction(self):
        # Pick an ephemeral port for testing
        test_port = 29323
        server = TCPHoneypotServer(
            host="127.0.0.1",
            port=test_port,
            session_mgr=self.session_mgr,
        )
        server.start()
        time.sleep(0.1)

        try:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(3.0)
            client.connect(("127.0.0.1", test_port))

            # Read banner & login prompt
            data = ""
            while "login:" not in data:
                chunk = client.recv(1024).decode("utf-8")
                if not chunk:
                    break
                data += chunk
            self.assertIn("Ubuntu", data)
            self.assertIn("login:", data)

            # Send username
            client.sendall(b"admin\n")
            time.sleep(0.05)

            # Read password prompt
            data_pass = client.recv(1024).decode("utf-8")
            self.assertIn("Password:", data_pass)

            # Send weak honey-password "admin123"
            client.sendall(b"admin123\n")
            time.sleep(0.1)

            # Read login success and welcome banner
            data_welcome = client.recv(2048).decode("utf-8")
            self.assertIn("Login successful", data_welcome)
            self.assertIn("admin@ip-10-0-1-42", data_welcome)

            # Execute a command in fake shell
            client.sendall(b"whoami\n")
            time.sleep(0.1)
            cmd_out = client.recv(1024).decode("utf-8")
            self.assertIn("admin", cmd_out)

            client.sendall(b"exit\n")
            time.sleep(0.05)
            client.close()

            # Verify session was properly tracked
            sessions = self.session_mgr.all_sessions()
            self.assertEqual(len(sessions), 1)
            sess = sessions[0]
            self.assertEqual(sess.protocol, "TELNET")
            self.assertTrue(sess.authenticated)
            self.assertEqual(sess.auth_user, "admin")
            self.assertEqual(len(sess.commands), 2)
            self.assertEqual(sess.commands[0].command, "whoami")
            self.assertEqual(sess.commands[1].command, "exit")

        finally:
            server.stop()

    def test_http_honeypot_interaction(self):
        test_port = 29080
        server = HTTPHoneypotServer(
            host="127.0.0.1",
            port=test_port,
            session_mgr=self.session_mgr,
        )
        server.start()
        time.sleep(0.1)

        try:
            # 1. Test GET /.env
            url = f"http://127.0.0.1:{test_port}/.env"
            req = urllib.request.Request(url, headers={"User-Agent": "BotnetScanner/2.0"})
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                content = resp.read().decode("utf-8")
                self.assertEqual(resp.status, 200)
                self.assertIn("AWS_ACCESS_KEY_ID", content)
                self.assertIn("DATABASE_URL", content)

            # 2. Test POST /login (credential brute-force)
            post_url = f"http://127.0.0.1:{test_port}/login"
            post_data = b"username=admin&password=admin123"
            req_post = urllib.request.Request(post_url, data=post_data, headers={"Content-Type": "application/x-www-form-urlencoded"})
            with urllib.request.urlopen(req_post, timeout=2.0) as resp_post:
                body = resp_post.read().decode("utf-8")
                self.assertEqual(resp_post.status, 200)
                self.assertIn("authenticated", body)

            # Verify recorded sessions
            sessions = self.session_mgr.all_sessions()
            self.assertGreaterEqual(len(sessions), 2)
            canary_sessions = [s for s in sessions if any("CANARY_ENV_FILE_LEAK" in c.canary_triggered or "" for c in s.commands if c.canary_triggered)]
            self.assertGreaterEqual(len(canary_sessions), 1)

        finally:
            server.stop()

    def test_ssh_honeypot_banner(self):
        test_port = 29222
        server = SSHHoneypotServer(
            host="127.0.0.1",
            port=test_port,
            session_mgr=self.session_mgr,
        )
        server.start()
        time.sleep(0.1)

        try:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(2.0)
            client.connect(("127.0.0.1", test_port))

            banner = client.recv(512).decode("utf-8")
            self.assertIn("SSH-2.0-OpenSSH_8.9p1", banner)

            # Client identification
            client.sendall(b"SSH-2.0-BotScanner_1.0\r\n")
            time.sleep(0.1)
            client.close()

            sessions = self.session_mgr.all_sessions()
            self.assertEqual(len(sessions), 1)
            self.assertEqual(sessions[0].protocol, "SSH")

        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
