"""Utilidad de línea de comandos para inspeccionar la base de datos local."""

from __future__ import annotations

import argparse
from typing import Iterable

from app import database


def cmd_user_count(_: argparse.Namespace) -> None:
    database.init_db()
    total = database.count_users()
    print(f"Usuarios registrados: {total}")


def cmd_list_users(_: argparse.Namespace) -> None:
    database.init_db()
    users = database.list_users()
    if not users:
        print("No hay usuarios registrados aún.")
        return
    for user in users:
        print(f"[{user.id}] {user.username} · creado el {user.created_at}")


def cmd_chat_count(_: argparse.Namespace) -> None:
    database.init_db()
    total = database.count_chats()
    print(f"Mensajes en el chat: {total}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("user-count", help="Muestra el número de usuarios registrados").set_defaults(
        func=cmd_user_count
    )
    subparsers.add_parser("list-users", help="Lista los usuarios registrados").set_defaults(func=cmd_list_users)
    subparsers.add_parser("chat-count", help="Indica cuántos mensajes se han almacenado").set_defaults(
        func=cmd_chat_count
    )
    return parser


def main(argv: Iterable[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
