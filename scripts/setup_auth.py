#!/usr/bin/env python
"""
ServiceNow Authentication Setup Menu

This script provides a menu to help users set up different authentication methods
for the ServiceNow MCP server.

Usage:
    python scripts/setup_auth.py
"""

import os
import re
import subprocess
import sys
from pathlib import Path


def clear_screen():
    """Clear the terminal screen."""
    os.system("cls" if os.name == "nt" else "clear")


def print_header():
    """Print the header for the menu."""
    print("=" * 60)
    print("ServiceNow MCP Server - Authentication Setup".center(60))
    print("=" * 60)
    print("\nThis script will help you set up authentication for your ServiceNow instance.")
    print("Choose one of the following authentication methods:\n")


def print_menu():
    """Print the menu options."""
    print("1. Basic Authentication (username/password)")
    print("2. OAuth Authentication (client ID/client secret)")
    print("3. API Key Authentication")
    print("4. Browser Authentication (MFA/SSO Support)")
    print("5. Test Current Configuration")
    print("6. Exit")
    print("\nEnter your choice (1-6): ", end="")


def setup_basic_auth():
    """Set up basic authentication."""
    clear_screen()
    print("=" * 60)
    print("Basic Authentication Setup".center(60))
    print("=" * 60)
    print("\nYou'll need your ServiceNow instance URL, username, and password.")

    instance_url = input("\nEnter your ServiceNow instance URL: ")
    username = input("Enter your ServiceNow username: ")
    password = input("Enter your ServiceNow password: ")

    # Update .env file
    env_path = Path(__file__).parent.parent / ".env"

    if env_path.exists():
        with open(env_path, "r") as f:
            env_content = f.read()
    else:
        env_content = "SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com\nSERVICENOW_AUTH_TYPE=basic\n"

    # Update basic authentication configuration
    env_content = re.sub(
        r"SERVICENOW_INSTANCE_URL=.*", f"SERVICENOW_INSTANCE_URL={instance_url}", env_content
    )

    if "SERVICENOW_USERNAME=" in env_content:
        env_content = re.sub(
            r"SERVICENOW_USERNAME=.*", f"SERVICENOW_USERNAME={username}", env_content
        )
    else:
        env_content += f"\nSERVICENOW_USERNAME={username}"

    if "SERVICENOW_PASSWORD=" in env_content:
        env_content = re.sub(
            r"SERVICENOW_PASSWORD=.*", f"SERVICENOW_PASSWORD={password}", env_content
        )
    else:
        env_content += f"\nSERVICENOW_PASSWORD={password}"

    # Ensure auth type is set to basic
    env_content = re.sub(r"SERVICENOW_AUTH_TYPE=.*", "SERVICENOW_AUTH_TYPE=basic", env_content)

    with open(env_path, "w") as f:
        f.write(env_content)

    print("\n✅ Updated .env file with basic authentication configuration!")
    input("\nPress Enter to continue...")


def setup_browser_auth():
    """Set up browser-based authentication (MFA)."""
    clear_screen()
    print("=" * 60)
    print("Browser Authentication (MFA/SSO) Setup".center(60))
    print("=" * 60)
    print("\nThis method opens a browser for interactive login,")
    print("which is ideal for instances with MFA or SSO (e.g., Okta).")

    instance_url = input("\nEnter your ServiceNow instance URL: ")

    # Update .env file
    env_path = Path(__file__).parent.parent / ".env"

    if env_path.exists():
        with open(env_path, "r") as f:
            env_content = f.read()
    else:
        env_content = "SERVICENOW_INSTANCE_URL=https://your-instance.service-now.com\nSERVICENOW_AUTH_TYPE=basic\n"

    # Update instance URL
    env_content = re.sub(
        r"SERVICENOW_INSTANCE_URL=.*", f"SERVICENOW_INSTANCE_URL={instance_url}", env_content
    )

    # Set auth type to browser
    env_content = re.sub(r"SERVICENOW_AUTH_TYPE=.*", "SERVICENOW_AUTH_TYPE=browser", env_content)

    # Add default browser configs if missing
    if "SERVICENOW_BROWSER_HEADLESS" not in env_content:
        env_content += "\nSERVICENOW_BROWSER_HEADLESS=false"
    if "SERVICENOW_BROWSER_TIMEOUT" not in env_content:
        env_content += "\nSERVICENOW_BROWSER_TIMEOUT=120"
    if "SERVICENOW_BROWSER_SESSION_TTL" not in env_content:
        env_content += "\nSERVICENOW_BROWSER_SESSION_TTL=30"

    # Default user data directory for Windows/Generic
    default_dir = os.path.expanduser("~/.mfa-servicenow-browser")
    if "SERVICENOW_BROWSER_USER_DATA_DIR" not in env_content:
        env_content += f"\nSERVICENOW_BROWSER_USER_DATA_DIR={default_dir}"

    with open(env_path, "w") as f:
        f.write(env_content)

    print("\n✅ Updated .env file with Browser Authentication configuration!")
    print(f"   Sessions will be saved to: {default_dir}")
    input("\nPress Enter to continue...")


def main():
    """Main function to run the menu."""
    while True:
        clear_screen()
        print_header()
        print_menu()

        choice = input()

        if choice == "1":
            setup_basic_auth()
        elif choice == "2":
            # Run the OAuth setup script
            subprocess.run([sys.executable, str(Path(__file__).parent / "setup_oauth.py")])
            input("\nPress Enter to continue...")
        elif choice == "3":
            # Run the API key setup script
            subprocess.run([sys.executable, str(Path(__file__).parent / "setup_api_key.py")])
            input("\nPress Enter to continue...")
        elif choice == "4":
            setup_browser_auth()
        elif choice == "5":
            # Run the test connection script
            clear_screen()
            print("Testing current configuration...\n")
            subprocess.run([sys.executable, str(Path(__file__).parent / "test_connection.py")])
            input("\nPress Enter to continue...")
        elif choice == "6":
            clear_screen()
            print("Exiting...")
            break
        else:
            print("Invalid choice. Please try again.")
            input("\nPress Enter to continue...")


if __name__ == "__main__":
    main()
