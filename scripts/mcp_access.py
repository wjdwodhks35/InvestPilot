"""Operator-only local provisioning. Never automatically link by email."""
import argparse
import os
from dotenv import load_dotenv
from app.auth import AuthStore
from app.mcp_access import MCPAccess
from app.mcp_server import https_url

def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description='Provision or revoke user consent for read-only MCP')
    parser.add_argument('action', choices=['link', 'revoke'])
    parser.add_argument('--username', required=True)
    parser.add_argument('--subject')
    parser.add_argument('--consent-confirmed', action='store_true')
    args = parser.parse_args()
    access = MCPAccess(AuthStore(os.getenv('INVESTPILOT_AUTH_DB', 'data/auth.db')))
    if args.action == 'link':
        if not args.subject or not args.consent_confirmed:
            parser.error('Verified OAuth subject and explicit user consent are required')
        access.link(https_url(os.environ['INVESTPILOT_MCP_ISSUER']), args.subject, args.username)
    else:
        access.revoke(args.username)
    print('MCP access updated; no credentials displayed.')

if __name__ == '__main__':
    main()
