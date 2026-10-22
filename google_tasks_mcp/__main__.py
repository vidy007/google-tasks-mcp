"""CLI: `google-tasks-mcp` runs the server over stdio; subcommands manage authorization."""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    p = argparse.ArgumentParser(prog="google-tasks-mcp")
    sub = p.add_subparsers(dest="cmd")
    a = sub.add_parser("auth", help="sign in to Google once in the browser and store a token")
    a.add_argument("--client-secret", required=True, help="OAuth client JSON from Google Cloud Console")
    a.add_argument("--keep-client-secret", action="store_true", help="do not delete the JSON after use")
    sub.add_parser("status", help="check that the stored token works")
    sub.add_parser("logout", help="revoke the token at Google and delete it locally")
    sub.add_parser("serve", help="run the MCP server over stdio (default)")
    args = p.parse_args()

    if args.cmd == "auth":
        from .auth import run_oauth_flow

        path = run_oauth_flow(args.client_secret, delete_client_secret=not args.keep_client_secret)
        print(f"Authorized. Token saved to {path} (readable only by you).")
        if not args.keep_client_secret:
            print(f"Deleted {args.client_secret}.")
    elif args.cmd == "status":
        from .server import _svc

        lists = _svc().task_lists()
        print(f"OK: {len(lists)} task list(s): " + ", ".join(t["title"] for t in lists))
    elif args.cmd == "logout":
        from .auth import logout

        print("Token revoked and deleted." if logout() else "No stored token.")
    else:
        from .server import run

        run()


if __name__ == "__main__":
    sys.exit(main())
