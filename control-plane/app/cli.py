"""Account administration from the host (anyone who can run this already controls the server).

    docker compose exec control-plane python -m app.cli list
    docker compose exec control-plane python -m app.cli create <username> [--admin]
    docker compose exec control-plane python -m app.cli reset-password <username>
    docker compose exec control-plane python -m app.cli delete <username>

New and reset passwords are generated and printed once.
"""

import argparse
import secrets
import sys

from . import config
from .security import USERNAME_PATTERN, hash_password
from .store import Store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="Manage OwnCloud accounts")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    create = commands.add_parser("create")
    create.add_argument("username")
    create.add_argument("--admin", action="store_true")
    reset = commands.add_parser("reset-password")
    reset.add_argument("username")
    delete = commands.add_parser("delete")
    delete.add_argument("username")
    args = parser.parse_args(argv)

    store = Store(config.DATA_DIR / "owncloud.db")
    if args.command == "list":
        for user in store.list_users():
            state = "disabled" if user["disabled"] else "active"
            print(f"{user['username']:32} {user['role']:6} {state:8} {user['app_count']} app(s)")
        return 0

    username = args.username.strip().lower()
    if not USERNAME_PATTERN.match(username):
        print("Usernames are 3–32 characters: lowercase letters, digits, '.', '_' or '-'", file=sys.stderr)
        return 2
    user = store.user_by_name(username)

    if args.command == "create":
        if user:
            print("This username is taken", file=sys.stderr)
            return 1
        password = secrets.token_urlsafe(18)
        store.create_user(username, *hash_password(password), "admin" if args.admin else "user")
        print(password)
        return 0
    if user is None:
        print("No such user", file=sys.stderr)
        return 1
    if args.command == "reset-password":
        password = secrets.token_urlsafe(18)
        salt, password_hash = hash_password(password)
        store.update_user(user["id"], salt=salt, password_hash=password_hash)
        store.delete_user_tokens(user["id"])
        print(password)
        print("Existing browser sessions end when the control plane restarts; access tokens were revoked.", file=sys.stderr)
        return 0
    if store.list_apps(user["id"]):
        print("Delete this user from the console (it removes their apps too)", file=sys.stderr)
        return 1
    store.delete_user(user["id"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
