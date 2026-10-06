"""Legacy app tests explicitly use local-only development mode.

Dedicated authentication tests create isolated apps with authentication enabled.
"""
import os
os.environ['INVESTPILOT_AUTH_ENABLED']='false'
