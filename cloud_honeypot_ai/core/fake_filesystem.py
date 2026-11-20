"""Simulated in-memory Linux filesystem with canary honey-tokens."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from cloud_honeypot_ai.config import CONFIG


@dataclass
class FakeFile:
    """Represents a virtual file or directory in the simulated filesystem."""
    name: str
    is_dir: bool = False
    content: str = ""
    permissions: str = "-rw-r--r--"
    owner: str = "root"
    group: str = "root"
    size: int = 0
    canary_tag: Optional[str] = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%b %d %H:%M")
    )


class FakeFilesystem:
    """Virtual Linux filesystem tailored for cloud honeypot deception."""

    def __init__(self):
        self.files: Dict[str, FakeFile] = {}
        self._initialize_default_tree()

    def _initialize_default_tree(self) -> None:
        """Create standard Linux directory structure and realistic decoy files."""
        # Standard directories
        standard_dirs = [
            "/",
            "/bin",
            "/boot",
            "/dev",
            "/etc",
            "/etc/ssl",
            "/etc/ssh",
            "/home",
            "/home/ubuntu",
            "/home/ubuntu/.aws",
            "/home/ubuntu/.ssh",
            "/root",
            "/root/.ssh",
            "/var",
            "/var/log",
            "/var/www",
            "/var/backups",
            "/var/data",
            "/tmp",
            "/opt",
            "/opt/cloud_engine",
            "/docs",
            "/usr",
            "/usr/bin",
            "/usr/local",
            "/app",
        ]
        for d in standard_dirs:
            self.files[d] = FakeFile(
                name=d.split("/")[-1] or "/",
                is_dir=True,
                permissions="drwxr-xr-x",
                owner="root" if not d.startswith("/home/ubuntu") else "ubuntu",
                group="root" if not d.startswith("/home/ubuntu") else "ubuntu",
            )

        # /etc/passwd
        self.files["/etc/passwd"] = FakeFile(
            name="passwd",
            content=(
                "root:x:0:0:root:/root:/bin/bash\n"
                "daemon:x:1:1:daemon:/usr/sbin:/usr/sbin/nologin\n"
                "bin:x:2:2:bin:/bin:/usr/sbin/nologin\n"
                "sys:x:3:3:sys:/dev:/usr/sbin/nologin\n"
                "sync:x:4:65534:sync:/bin:/bin/sync\n"
                "games:x:5:60:games:/usr/games:/usr/sbin/nologin\n"
                "man:x:6:12:man:/var/cache/man:/usr/sbin/nologin\n"
                "lp:x:7:7:lp:/var/spool/lpd:/usr/sbin/nologin\n"
                "mail:x:8:8:mail:/var/mail:/usr/sbin/nologin\n"
                "news:x:9:9:news:/var/spool/news:/usr/sbin/nologin\n"
                "uucp:x:10:10:uucp:/var/spool/uucp:/usr/sbin/nologin\n"
                "proxy:x:13:13:proxy:/bin:/usr/sbin/nologin\n"
                "www-data:x:33:33:www-data:/var/www:/usr/sbin/nologin\n"
                "backup:x:34:34:backup:/var/backups:/usr/sbin/nologin\n"
                "list:x:38:38:Mailing List Manager:/var/list:/usr/sbin/nologin\n"
                "irc:x:39:39:ircd:/run/ircd:/usr/sbin/nologin\n"
                "gnats:x:41:41:Gnats Bug-Reporting System (admin):/var/lib/gnats:/usr/sbin/nologin\n"
                "nobody:x:65534:65534:nobody:/nonexistent:/usr/sbin/nologin\n"
                "systemd-network:x:100:102:systemd Network Management,,,:/run/systemd:/usr/sbin/nologin\n"
                "systemd-resolve:x:101:103:systemd Resolver,,,:/run/systemd:/usr/sbin/nologin\n"
                "ubuntu:x:1000:1000:Ubuntu Cloud User:/home/ubuntu:/bin/bash\n"
                "sshd:x:109:65534::/run/sshd:/usr/sbin/nologin\n"
            ),
            permissions="-rw-r--r--",
            size=1420,
        )

        # /etc/shadow (Canary Honeypot Target)
        self.files["/etc/shadow"] = FakeFile(
            name="shadow",
            content=(
                "root:$6$rounds=4096$canarysalt$qP7n2P0yMv81tKz2/N00O4eZ912x...:19420:0:99999:7:::\n"
                "daemon:*:19420:0:99999:7:::\n"
                "bin:*:19420:0:99999:7:::\n"
                "sys:*:19420:0:99999:7:::\n"
                "sync:*:19420:0:99999:7:::\n"
                "ubuntu:$6$rounds=4096$cloudsalt$fG8m1x0yAv99kLz1...:19420:0:99999:7:::\n"
            ),
            permissions="-rw-r-----",
            size=680,
            canary_tag="HONEY_SHADOW_EXFILTRATION",
        )

        # /etc/os-release
        self.files["/etc/os-release"] = FakeFile(
            name="os-release",
            content=(
                f'NAME="{CONFIG.os_name}"\n'
                'VERSION="22.04.4 LTS (Jammy Jellyfish)"\n'
                'ID=ubuntu\n'
                'ID_LIKE=debian\n'
                'PRETTY_NAME="Ubuntu 22.04.4 LTS"\n'
                'VERSION_ID="22.04"\n'
                'HOME_URL="https://www.ubuntu.com/"\n'
            ),
            permissions="-rw-r--r--",
            size=280,
        )

        # /etc/hostname
        self.files["/etc/hostname"] = FakeFile(
            name="hostname",
            content=f"{CONFIG.hostname}\n",
            permissions="-rw-r--r--",
            size=len(CONFIG.hostname) + 1,
        )

        # /etc/hosts
        self.files["/etc/hosts"] = FakeFile(
            name="hosts",
            content=(
                "127.0.0.1 localhost\n"
                f"10.0.1.42 {CONFIG.hostname}\n"
                "10.0.0.2  aws-dns-resolver.internal\n"
                "10.0.2.15 prod-db.internal\n"
            ),
            permissions="-rw-r--r--",
            size=150,
        )

        # /home/ubuntu/.aws/credentials (High-Value Canary Honey-Token)
        self.files["/home/ubuntu/.aws/credentials"] = FakeFile(
            name="credentials",
            content=(
                "[default]\n"
                f"aws_access_key_id = {CONFIG.canary_aws_key_id}\n"
                f"aws_secret_access_key = {CONFIG.canary_aws_secret}\n"
                "region = eu-west-1\n"
            ),
            permissions="-rw-------",
            owner="ubuntu",
            group="ubuntu",
            size=142,
            canary_tag="CANARY_AWS_CREDENTIAL_STOLEN",
        )

        # /app/.env (Decoy cloud application config)
        self.files["/app/.env"] = FakeFile(
            name=".env",
            content=(
                "NODE_ENV=production\n"
                "PORT=3000\n"
                f"DATABASE_URL={CONFIG.canary_db_connection}\n"
                "JWT_SECRET=super_secret_picoas_cloud_jwt_key_2026\n"
                f"AWS_ACCESS_KEY_ID={CONFIG.canary_aws_key_id}\n"
                f"AWS_SECRET_ACCESS_KEY={CONFIG.canary_aws_secret}\n"
            ),
            permissions="-rw-r--r--",
            owner="ubuntu",
            group="ubuntu",
            size=240,
            canary_tag="CANARY_ENV_FILE_LEAK",
        )

        # /home/ubuntu/.bash_history (Realistic breadcrumbs)
        self.files["/home/ubuntu/.bash_history"] = FakeFile(
            name=".bash_history",
            content=(
                "sudo apt update && sudo apt upgrade -y\n"
                "curl -s https://get.docker.com | bash\n"
                "docker ps\n"
                "cd /app && ls -la\n"
                "cat .env\n"
                "git status\n"
                "pg_dump -h prod-db.internal -U dbadmin customers > /var/backups/customers_dump.sql\n"
                "cat /docs/README_arquitetura.md\n"
            ),
            permissions="-rw-------",
            owner="ubuntu",
            group="ubuntu",
            size=260,
        )

        # Active Deception Assets:
        from cloud_honeypot_ai.deception.honey_database import HONEY_DB_GENERATOR
        from cloud_honeypot_ai.deception.defensive_prompt_poison import DEFENSIVE_POISONER
        from cloud_honeypot_ai.deception.telemetry_beacon import TELEMETRY_BEACON_MGR

        # 1. Armadilha 1: Base de dados com Células Vivas
        db_dump = HONEY_DB_GENERATOR.generate_customers_dump(session_id="env_default_01")
        self.files["/var/backups/customers_dump.sql"] = FakeFile(
            name="customers_dump.sql",
            content=db_dump.sql_content,
            permissions="-rw-r--r--",
            size=len(db_dump.sql_content),
            canary_tag="LIVING_CELL_HONEY_DATABASE_SQL",
        )
        self.files["/var/data/employees_export.csv"] = FakeFile(
            name="employees_export.csv",
            content=db_dump.csv_content,
            permissions="-rw-r--r--",
            size=len(db_dump.csv_content),
            canary_tag="LIVING_CELL_EMPLOYEES_CSV",
        )

        # 2. Armadilha 2: Documentação com Prompt Injection Defensivo
        poisoned_doc = DEFENSIVE_POISONER.generate_architecture_doc(session_id="env_default_01")
        self.files["/docs/README_arquitetura.md"] = FakeFile(
            name="README_arquitetura.md",
            content=poisoned_doc.document_content,
            permissions="-rw-r--r--",
            size=len(poisoned_doc.document_content),
            canary_tag="DEFENSIVE_PROMPT_POISON_DOC",
        )

        # 3. Armadilha 3: Projeto com Beacons de Telemetria
        beacon_files = TELEMETRY_BEACON_MGR.generate_decoy_project_files(session_id="env_default_01")
        for path_str, content_str in beacon_files.items():
            self.files[path_str] = FakeFile(
                name=path_str.split("/")[-1],
                content=content_str,
                permissions="-rwxr-xr-x",
                size=len(content_str),
                canary_tag="TELEMETRY_BEACON_PROJECT",
            )

    def _normalize_path(self, path: str, cwd: str = "/home/ubuntu") -> str:
        """Resolve relative and absolute paths into canonical path."""
        if not path:
            return cwd
        if path.startswith("~/"):
            path = "/home/ubuntu" + path[1:]
        elif path == "~":
            path = "/home/ubuntu"

        if not path.startswith("/"):
            combined = f"{cwd.rstrip('/')}/{path}"
        else:
            combined = path

        parts = []
        for part in combined.split("/"):
            if not part or part == ".":
                continue
            if part == "..":
                if parts:
                    parts.pop()
            else:
                parts.append(part)
        return "/" + "/".join(parts)

    def exists(self, path: str, cwd: str = "/home/ubuntu") -> bool:
        canonical = self._normalize_path(path, cwd)
        return canonical in self.files

    def is_dir(self, path: str, cwd: str = "/home/ubuntu") -> bool:
        canonical = self._normalize_path(path, cwd)
        f = self.files.get(canonical)
        return f.is_dir if f else False

    def read_file(self, path: str, cwd: str = "/home/ubuntu") -> Tuple[Optional[str], Optional[str]]:
        """Read file content and return (content, canary_tag)."""
        canonical = self._normalize_path(path, cwd)
        f = self.files.get(canonical)
        if not f:
            return None, None
        if f.is_dir:
            return None, None
        return f.content, f.canary_tag

    def list_dir(self, path: str, cwd: str = "/home/ubuntu") -> Optional[List[FakeFile]]:
        """List files in directory."""
        canonical = self._normalize_path(path, cwd)
        if canonical not in self.files or not self.files[canonical].is_dir:
            return None

        prefix = canonical.rstrip("/") + "/"
        entries = []
        for p, file_obj in self.files.items():
            if p == canonical:
                continue
            if p.startswith(prefix):
                # Ensure it's a direct child
                remainder = p[len(prefix):]
                if "/" not in remainder:
                    entries.append(file_obj)
        return sorted(entries, key=lambda x: (not x.is_dir, x.name))

    def write_file(
        self,
        path: str,
        content: str,
        cwd: str = "/home/ubuntu",
        owner: str = "ubuntu",
        canary_tag: Optional[str] = None,
    ) -> bool:
        """Write or overwrite a virtual file."""
        canonical = self._normalize_path(path, cwd)
        name = canonical.split("/")[-1]
        self.files[canonical] = FakeFile(
            name=name,
            is_dir=False,
            content=content,
            permissions="-rw-r--r--",
            owner=owner,
            group=owner,
            size=len(content.encode("utf-8")),
            canary_tag=canary_tag,
        )
        return True

    def make_dir(self, path: str, cwd: str = "/home/ubuntu", owner: str = "ubuntu") -> bool:
        """Create a virtual directory."""
        canonical = self._normalize_path(path, cwd)
        if canonical in self.files:
            return False
        name = canonical.split("/")[-1]
        self.files[canonical] = FakeFile(
            name=name,
            is_dir=True,
            permissions="drwxr-xr-x",
            owner=owner,
            group=owner,
        )
        return True
