"""Machine learning and heuristic classifier for Bot vs Human attacker profiling."""

from dataclasses import dataclass
import re
from typing import Dict, List, Tuple


@dataclass
class AttackerProfile:
    """Classification of the attacker persona and confidence score."""
    classification: str  # AUTOMATED_BOTNET, SCRIPT_KIDDIE, TARGETED_APT, RECON_SCANNER
    confidence: float    # 0.0 to 1.0
    is_automated: bool
    characteristics: List[str]
    velocity_score: float  # Commands per minute / millisecond execution speed


class BotClassifier:
    """Profiles attacker based on behavioral patterns, speed, and command entropy."""

    # Known signature commands used by automated botnets (Mirai, Mozi, Kinsing, etc.)
    BOTNET_PATTERNS = [
        re.compile(r"wget\s+.*(http|ftp|sh|bin|arm|mips|x86)", re.I),
        re.compile(r"curl\s+.*\|\s*(sh|bash)", re.I),
        re.compile(r"chmod\s+(\+x|777|755)\s+.*(/tmp|/var/run)", re.I),
        re.compile(r"cd\s+(/tmp|/var/run|/dev/shm)\s*(;|&&)", re.I),
        re.compile(r"rm\s+(-rf|-f)\s+.*(/tmp|/var/run)", re.I),
        re.compile(r"cat\s+/proc/cpuinfo", re.I),
        re.compile(r"cat\s+/proc/mounts", re.I),
        re.compile(r"killall\s+-9", re.I),
        re.compile(r"pkill\s+", re.I),
        re.compile(r"crontab\s+-l", re.I),
        re.compile(r"(xmrig|stratum\+tcp|monero)", re.I),
    ]

    # Reconnaissance commands typical of automated mass scanners
    SCANNER_PATTERNS = [
        re.compile(r"^whoami$", re.I),
        re.compile(r"^id$", re.I),
        re.compile(r"^uname\s+-a$", re.I),
        re.compile(r"^cat\s+/etc/issue$", re.I),
        re.compile(r"^exit$", re.I),
    ]

    def profile_session(
        self,
        auth_attempts: List[Dict],
        commands: List[Dict],
        duration_seconds: float,
    ) -> AttackerProfile:
        """Classify session into AUTOMATED_BOTNET, SCRIPT_KIDDIE, or TARGETED_APT."""
        characteristics = []
        num_commands = len(commands)
        num_auths = len(auth_attempts)

        # 1. Velocity Analysis (Commands per minute)
        cpm = 0.0
        if duration_seconds > 0:
            cpm = (num_commands / duration_seconds) * 60.0
        elif num_commands > 1:
            cpm = 120.0  # Burst execution in sub-second

        if cpm > 40.0:
            characteristics.append(f"High command velocity ({cpm:.1f} cmd/min), typical of automated scripts")

        # 2. Brute-force burst check
        if num_auths >= 3:
            characteristics.append(f"Credential brute-forcing detected ({num_auths} password attempts)")

        # 3. Pattern Matching
        bot_hits = 0
        scanner_hits = 0
        cmd_texts = [c.get("command", "") for c in commands]

        for cmd in cmd_texts:
            for p in self.BOTNET_PATTERNS:
                if p.search(cmd):
                    bot_hits += 1
                    characteristics.append(f"Botnet worm pattern matched: '{cmd[:40]}...'")
                    break
            for sp in self.SCANNER_PATTERNS:
                if sp.match(cmd.strip()):
                    scanner_hits += 1
                    break

        # 4. Interactive Human Indicators (typos, backspaces, clear, history exploration)
        human_indicators = 0
        for cmd in cmd_texts:
            if any(term in cmd for term in ("ls -la", "cd ..", "nano", "vim", "cat .bash_history")):
                human_indicators += 1

        # Decision Logic
        if bot_hits >= 2 or (cpm > 50.0 and bot_hits >= 1):
            return AttackerProfile(
                classification="AUTOMATED_BOTNET",
                confidence=0.95,
                is_automated=True,
                characteristics=characteristics or ["Automated malicious malware dropper sequence"],
                velocity_score=cpm,
            )

        if bot_hits >= 1 or cpm > 30.0:
            return AttackerProfile(
                classification="AUTOMATED_BOTNET",
                confidence=0.85,
                is_automated=True,
                characteristics=characteristics,
                velocity_score=cpm,
            )

        if num_commands <= 3 and scanner_hits >= 1 and human_indicators == 0:
            return AttackerProfile(
                classification="RECON_SCANNER",
                confidence=0.88,
                is_automated=True,
                characteristics=characteristics + ["Mass internet reconnaissance probe"],
                velocity_score=cpm,
            )

        if human_indicators >= 2:
            return AttackerProfile(
                classification="TARGETED_APT",
                confidence=0.82,
                is_automated=False,
                characteristics=characteristics + ["Interactive human attacker performing targeted exploration"],
                velocity_score=cpm,
            )

        # Default classification
        return AttackerProfile(
            classification="SCRIPT_KIDDIE",
            confidence=0.75,
            is_automated=False,
            characteristics=characteristics or ["Manual execution of basic exploitation commands"],
            velocity_score=cpm,
        )


# Singleton instance
BOT_CLASSIFIER = BotClassifier()
