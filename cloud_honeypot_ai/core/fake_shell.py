"""Simulated bash/sh interactive shell for attacker interaction."""

from dataclasses import dataclass, field
import re
import shlex
from typing import Dict, List, Optional, Tuple

from cloud_honeypot_ai.config import CONFIG
from cloud_honeypot_ai.core.fake_filesystem import FakeFilesystem


@dataclass
class ShellResult:
    """Result of executing a command in the fake shell."""
    stdout: str
    exit_code: int = 0
    canary_triggered: Optional[str] = None
    should_exit: bool = False


class FakeShell:
    """Realistic bash command execution engine."""

    def __init__(self, username: str = "ubuntu", initial_cwd: Optional[str] = None):
        self.username = username
        self.cwd = initial_cwd or ("/root" if username == "root" else f"/home/{username}")
        self.fs = FakeFilesystem()
        self.history: List[str] = []
        self.env: Dict[str, str] = {
            "USER": self.username,
            "HOME": "/root" if self.username == "root" else f"/home/{self.username}",
            "SHELL": "/bin/bash",
            "TERM": "xterm-256color",
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "PWD": self.cwd,
        }

    def get_prompt(self) -> str:
        """Return bash prompt (e.g. 'ubuntu@ip-10-0-1-42:~$ ' or 'root@ip-10-0-1-42:~# ')."""
        symbol = "#" if self.username == "root" else "$"
        display_cwd = "~" if self.cwd == self.env["HOME"] else self.cwd
        return f"{self.username}@{CONFIG.hostname}:{display_cwd}{symbol} "

    def execute(self, cmd_line: str) -> ShellResult:
        """Parse and execute a shell command line."""
        cmd_raw = cmd_line.strip()
        if not cmd_raw:
            return ShellResult(stdout="")

        self.history.append(cmd_raw)

        # Check for exit / logout
        if cmd_raw in ("exit", "logout", "quit"):
            return ShellResult(stdout="logout\n", should_exit=True)

        # Handle simple output redirection: cmd > file or cmd >> file
        redirect_file = None
        append_mode = False
        if " >> " in cmd_raw:
            parts = cmd_raw.split(" >> ", 1)
            cmd_raw, redirect_file = parts[0].strip(), parts[1].strip()
            append_mode = True
        elif " > " in cmd_raw:
            parts = cmd_raw.split(" > ", 1)
            cmd_raw, redirect_file = parts[0].strip(), parts[1].strip()
            append_mode = False

        # Handle chained commands (e.g., cmd1 && cmd2 or cmd1; cmd2)
        if " && " in cmd_raw:
            subcmds = cmd_raw.split(" && ")
            outputs = []
            canary = None
            for sc in subcmds:
                res = self._execute_single(sc.strip())
                if res.canary_triggered:
                    canary = res.canary_triggered
                outputs.append(res.stdout)
                if res.exit_code != 0 or res.should_exit:
                    return ShellResult(
                        stdout="".join(outputs),
                        exit_code=res.exit_code,
                        canary_triggered=canary,
                        should_exit=res.should_exit,
                    )
            return ShellResult(stdout="".join(outputs), canary_triggered=canary)

        if " ; " in cmd_raw or "; " in cmd_raw:
            subcmds = [s.strip() for s in re.split(r";\s*", cmd_raw) if s.strip()]
            outputs = []
            canary = None
            for sc in subcmds:
                res = self._execute_single(sc)
                if res.canary_triggered:
                    canary = res.canary_triggered
                outputs.append(res.stdout)
                if res.should_exit:
                    break
            return ShellResult(stdout="".join(outputs), canary_triggered=canary)

        res = self._execute_single(cmd_raw)

        # Apply redirection if specified
        if redirect_file:
            content_to_write = res.stdout
            if append_mode:
                existing, _ = self.fs.read_file(redirect_file, self.cwd)
                if existing:
                    content_to_write = existing + content_to_write
            self.fs.write_file(redirect_file, content_to_write, self.cwd, owner=self.username)
            return ShellResult(stdout="", canary_triggered=res.canary_triggered)

        return res

    def _execute_single(self, cmd_line: str) -> ShellResult:
        """Execute a single atomic command."""
        try:
            tokens = shlex.split(cmd_line)
        except Exception:
            tokens = cmd_line.split()

        if not tokens:
            return ShellResult(stdout="")

        cmd = tokens[0]
        args = tokens[1:]

        # Dispatch table
        handlers = {
            "whoami": self._cmd_whoami,
            "id": self._cmd_id,
            "uname": self._cmd_uname,
            "pwd": self._cmd_pwd,
            "cd": self._cmd_cd,
            "ls": self._cmd_ls,
            "cat": self._cmd_cat,
            "ps": self._cmd_ps,
            "top": self._cmd_top,
            "htop": self._cmd_top,
            "uptime": self._cmd_uptime,
            "df": self._cmd_df,
            "free": self._cmd_free,
            "ifconfig": self._cmd_ifconfig,
            "ip": self._cmd_ip,
            "netstat": self._cmd_netstat,
            "ss": self._cmd_netstat,
            "w": self._cmd_w,
            "who": self._cmd_w,
            "last": self._cmd_last,
            "echo": self._cmd_echo,
            "curl": self._cmd_curl_wget,
            "wget": self._cmd_curl_wget,
            "chmod": self._cmd_chmod,
            "mkdir": self._cmd_mkdir,
            "touch": self._cmd_touch,
            "rm": self._cmd_rm,
            "history": self._cmd_history,
            "sudo": self._cmd_sudo,
            "su": self._cmd_su,
            "sh": self._cmd_sh_bash,
            "bash": self._cmd_sh_bash,
            "python": self._cmd_python,
            "python3": self._cmd_python,
            "env": self._cmd_env,
            "export": self._cmd_export,
            "clear": lambda a: ShellResult(stdout="\033[H\033[2J"),
        }

        handler = handlers.get(cmd)
        if handler:
            return handler(args)

        # Fallback for unknown or simulated binary
        return ShellResult(
            stdout=f"bash: {cmd}: command not found\n",
            exit_code=127,
        )

    # --- Built-in command handlers ---

    def _cmd_whoami(self, args: List[str]) -> ShellResult:
        return ShellResult(stdout=f"{self.username}\n")

    def _cmd_id(self, args: List[str]) -> ShellResult:
        if self.username == "root":
            return ShellResult(stdout="uid=0(root) gid=0(root) groups=0(root)\n")
        return ShellResult(
            stdout="uid=1000(ubuntu) gid=1000(ubuntu) groups=1000(ubuntu),4(adm),24(cdrom),27(sudo),30(dip),46(plugdev),110(lxd)\n"
        )

    def _cmd_uname(self, args: List[str]) -> ShellResult:
        if "-a" in args:
            return ShellResult(
                stdout=f"Linux {CONFIG.hostname} {CONFIG.kernel_release} #105-Ubuntu SMP Mon Mar 18 15:44:52 UTC 2026 {CONFIG.architecture} GNU/Linux\n"
            )
        if "-r" in args:
            return ShellResult(stdout=f"{CONFIG.kernel_release}\n")
        if "-m" in args:
            return ShellResult(stdout=f"{CONFIG.architecture}\n")
        return ShellResult(stdout="Linux\n")

    def _cmd_pwd(self, args: List[str]) -> ShellResult:
        return ShellResult(stdout=f"{self.cwd}\n")

    def _cmd_cd(self, args: List[str]) -> ShellResult:
        target = args[0] if args else self.env["HOME"]
        if target == "~":
            target = self.env["HOME"]
        new_path = self.fs._normalize_path(target, self.cwd)
        if self.fs.exists(new_path) and self.fs.is_dir(new_path):
            self.cwd = new_path
            self.env["PWD"] = self.cwd
            return ShellResult(stdout="")
        return ShellResult(stdout=f"bash: cd: {target}: No such file or directory\n", exit_code=1)

    def _cmd_ls(self, args: List[str]) -> ShellResult:
        show_all = any("-a" in a for a in args)
        long_format = any("-l" in a for a in args)
        target = next((a for a in args if not a.startswith("-")), self.cwd)

        norm_target = self.fs._normalize_path(target, self.cwd)
        if not self.fs.exists(norm_target):
            return ShellResult(stdout=f"ls: cannot access '{target}': No such file or directory\n", exit_code=2)

        if not self.fs.is_dir(norm_target):
            file_obj = self.fs.files[norm_target]
            if long_format:
                return ShellResult(
                    stdout=f"{file_obj.permissions} 1 {file_obj.owner} {file_obj.group} {file_obj.size:5d} {file_obj.created_at} {file_obj.name}\n"
                )
            return ShellResult(stdout=f"{file_obj.name}\n")

        files = self.fs.list_dir(norm_target) or []
        if not show_all:
            files = [f for f in files if not f.name.startswith(".")]

        if long_format:
            lines = [f"total {len(files) * 4}"]
            for f in files:
                lines.append(
                    f"{f.permissions} 1 {f.owner} {f.group} {f.size:5d} {f.created_at} {f.name}"
                )
            return ShellResult(stdout="\n".join(lines) + "\n")

        names = [f.name for f in files]
        return ShellResult(stdout="  ".join(names) + "\n" if names else "")

    def _cmd_cat(self, args: List[str]) -> ShellResult:
        if not args:
            return ShellResult(stdout="")
        target = args[0]
        content, canary = self.fs.read_file(target, self.cwd)
        if content is None:
            if self.fs.is_dir(target, self.cwd):
                return ShellResult(stdout=f"cat: {target}: Is a directory\n", exit_code=1)
            return ShellResult(stdout=f"cat: {target}: No such file or directory\n", exit_code=1)
        return ShellResult(stdout=content, canary_triggered=canary)

    def _cmd_ps(self, args: List[str]) -> ShellResult:
        return ShellResult(
            stdout=(
                "USER         PID %CPU %MEM    VSZ   RSS TTY      STAT START   TIME COMMAND\n"
                "root           1  0.0  0.4 168432 11920 ?        Ss   09:12   0:02 /sbin/init\n"
                "root         412  0.0  0.2  29480  6480 ?        Ss   09:12   0:00 /lib/systemd/systemd-journald\n"
                "root         789  0.0  0.1  14280  3520 ?        Ss   09:12   0:00 /usr/sbin/sshd -D\n"
                "root        1024  0.0  0.3 224512  8910 ?        Ssl  09:13   0:01 /usr/bin/dockerd\n"
                f"{self.username}     2410  0.0  0.1  11420  3240 pts/0    Ss   10:14   0:00 -bash\n"
                f"{self.username}     2495  0.0  0.0  13512  2100 pts/0    R+   10:15   0:00 ps {' '.join(args)}\n"
            )
        )

    def _cmd_top(self, args: List[str]) -> ShellResult:
        return ShellResult(
            stdout=(
                "top - 10:18:24 up  1:06,  1 user,  load average: 0.08, 0.03, 0.01\n"
                "Tasks: 104 total,   1 running, 103 sleeping,   0 stopped,   0 zombie\n"
                "%Cpu(s):  1.2 us,  0.8 sy,  0.0 ni, 97.8 id,  0.1 wa,  0.0 hi,  0.1 si\n"
                "MiB Mem :   1984.2 total,    842.1 free,    524.3 used,    617.8 buff/cache\n"
                "MiB Swap:   1024.0 total,   1024.0 free,      0.0 used.   1290.4 avail Mem\n"
            )
        )

    def _cmd_uptime(self, args: List[str]) -> ShellResult:
        return ShellResult(stdout=" 10:18:42 up  1:06,  1 user,  load average: 0.05, 0.03, 0.00\n")

    def _cmd_df(self, args: List[str]) -> ShellResult:
        return ShellResult(
            stdout=(
                "Filesystem     1K-blocks    Used Available Use% Mounted on\n"
                "/dev/root       40176464 6128400  34031680  16% /\n"
                "tmpfs             992100       0    992100   0% /dev/shm\n"
                "/dev/loop0         64896   64896         0 100% /snap/core20/2015\n"
            )
        )

    def _cmd_free(self, args: List[str]) -> ShellResult:
        return ShellResult(
            stdout=(
                "               total        used        free      shared  buff/cache   available\n"
                "Mem:         2031820      536840      862340        1240      632640     1321400\n"
                "Swap:        1048572           0     1048572\n"
            )
        )

    def _cmd_ifconfig(self, args: List[str]) -> ShellResult:
        return ShellResult(
            stdout=(
                "eth0: flags=4163<UP,BROADCAST,RUNNING,MULTICAST>  mtu 9001\n"
                "        inet 10.0.1.42  netmask 255.255.255.0  broadcast 10.0.1.255\n"
                "        inet6 fe80::844:2aff:fe12:3456  prefixlen 64  scopeid 0x20<link>\n"
                "        ether 0a:44:2a:12:34:56  txqueuelen 1000  (Ethernet)\n"
                "        RX packets 24102  bytes 18241094 (18.2 MB)\n"
                "        TX packets 19412  bytes 12948210 (12.9 MB)\n\n"
                "lo: flags=73<UP,LOOPBACK,RUNNING>  mtu 65536\n"
                "        inet 127.0.0.1  netmask 255.0.0.0\n"
                "        loop  txqueuelen 1000  (Local Loopback)\n"
            )
        )

    def _cmd_ip(self, args: List[str]) -> ShellResult:
        return self._cmd_ifconfig(args)

    def _cmd_netstat(self, args: List[str]) -> ShellResult:
        return ShellResult(
            stdout=(
                "Active Internet connections (only servers)\n"
                "Proto Recv-Q Send-Q Local Address           Foreign Address         State       PID/Program name\n"
                "tcp        0      0 0.0.0.0:22              0.0.0.0:*               LISTEN      789/sshd: /usr/sbin\n"
                "tcp        0      0 127.0.0.1:5432          0.0.0.0:*               LISTEN      912/postgres\n"
                "tcp        0      0 0.0.0.0:80              0.0.0.0:*               LISTEN      1044/nginx: master\n"
            )
        )

    def _cmd_w(self, args: List[str]) -> ShellResult:
        return ShellResult(
            stdout=(
                " 10:19:01 up  1:07,  1 user,  load average: 0.04, 0.02, 0.00\n"
                "USER     TTY      FROM             LOGIN@   IDLE   JCPU   PCPU WHAT\n"
                f"{self.username}    pts/0    198.235.24.42    10:14    1.00s  0.02s  0.00s w\n"
            )
        )

    def _cmd_last(self, args: List[str]) -> ShellResult:
        return ShellResult(
            stdout=(
                f"{self.username}    pts/0        198.235.24.42    Fri Nov 20 10:14   still logged in\n"
                "ubuntu   pts/0        10.0.0.15        Fri Nov 20 08:30 - 09:15  (00:45)\n"
                "reboot   system boot  5.15.0-101-gener Fri Nov 20 08:28   still running\n"
            )
        )

    def _cmd_echo(self, args: List[str]) -> ShellResult:
        return ShellResult(stdout=" ".join(args) + "\n")

    def _cmd_curl_wget(self, args: List[str]) -> ShellResult:
        """Simulate downloading attacker payloads / scripts."""
        url = next((a for a in args if a.startswith("http://") or a.startswith("https://")), "http://payload.sh")
        filename = url.split("/")[-1] or "script.sh"
        decoy_content = "#!/bin/sh\n# Captured malware dropper payload\necho 'payload executed'\n"
        self.fs.write_file(f"/tmp/{filename}", decoy_content, self.cwd, owner=self.username)
        return ShellResult(
            stdout=(
                f"--2026-11-20 10:19:12--  {url}\n"
                "Resolving host... 194.26.29.10\n"
                "Connecting to host... connected.\n"
                "HTTP request sent, awaiting response... 200 OK\n"
                f"Length: 104 [text/x-shellscript]\n"
                f"Saving to: '{filename}'\n"
                f"'{filename}' saved [104/104]\n"
            ),
            canary_triggered=f"DOWNLOADED_ATTACKER_PAYLOAD:{url}",
        )

    def _cmd_chmod(self, args: List[str]) -> ShellResult:
        return ShellResult(stdout="")

    def _cmd_mkdir(self, args: List[str]) -> ShellResult:
        if not args:
            return ShellResult(stdout="mkdir: missing operand\n", exit_code=1)
        for target in args:
            if not target.startswith("-"):
                self.fs.make_dir(target, self.cwd, self.username)
        return ShellResult(stdout="")

    def _cmd_touch(self, args: List[str]) -> ShellResult:
        for target in args:
            if not target.startswith("-"):
                if not self.fs.exists(target, self.cwd):
                    self.fs.write_file(target, "", self.cwd, self.username)
        return ShellResult(stdout="")

    def _cmd_rm(self, args: List[str]) -> ShellResult:
        return ShellResult(stdout="")

    def _cmd_history(self, args: List[str]) -> ShellResult:
        lines = [f"{i+1:5d}  {cmd}" for i, cmd in enumerate(self.history)]
        return ShellResult(stdout="\n".join(lines) + "\n" if lines else "")

    def _cmd_sudo(self, args: List[str]) -> ShellResult:
        if not args:
            return ShellResult(stdout="usage: sudo -h | -K | -k | -V\n")
        # Attacker escalates privilege
        if args[0] in ("su", "-i", "bash", "sh"):
            self.username = "root"
            self.cwd = "/root"
            self.env["USER"] = "root"
            self.env["HOME"] = "/root"
            self.env["PWD"] = "/root"
            return ShellResult(stdout="root privileges granted.\n", canary_triggered="PRIVILEGE_ESCALATION_TO_ROOT")
        # Run sub-command as root
        sub_res = self._execute_single(" ".join(args))
        return sub_res

    def _cmd_su(self, args: List[str]) -> ShellResult:
        self.username = "root"
        self.cwd = "/root"
        self.env["USER"] = "root"
        self.env["HOME"] = "/root"
        self.env["PWD"] = "/root"
        return ShellResult(stdout="", canary_triggered="PRIVILEGE_ESCALATION_TO_ROOT")

    def _cmd_sh_bash(self, args: List[str]) -> ShellResult:
        if "-c" in args:
            idx = args.index("-c")
            if idx + 1 < len(args):
                return self.execute(args[idx + 1])
        return ShellResult(stdout="")

    def _cmd_python(self, args: List[str]) -> ShellResult:
        if "-c" in args:
            idx = args.index("-c")
            if idx + 1 < len(args):
                return ShellResult(stdout="")
        return ShellResult(stdout="Python 3.10.12 (main, Nov 20 2026, 09:12:00) [GCC 11.4.0] on linux\nType \"help\", \"copyright\", \"credits\" or \"license\" for more information.\n>>> ")

    def _cmd_env(self, args: List[str]) -> ShellResult:
        lines = [f"{k}={v}" for k, v in self.env.items()]
        return ShellResult(stdout="\n".join(lines) + "\n")

    def _cmd_export(self, args: List[str]) -> ShellResult:
        for item in args:
            if "=" in item:
                k, v = item.split("=", 1)
                self.env[k] = v.strip('"').strip("'")
        return ShellResult(stdout="")
