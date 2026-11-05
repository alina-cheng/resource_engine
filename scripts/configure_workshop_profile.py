"""Interactive local-only setup of temporary Workshop Studio CLI credentials."""
import configparser
from getpass import getpass
import os
from pathlib import Path


def main():
    profile = input("Profile [workshop]: ").strip() or "workshop"
    if not profile.replace("-", "").replace("_", "").isalnum():
        raise SystemExit("Use letters, numbers, hyphens and underscores for the profile.")
    access = getpass("AWS access key ID: ").strip()
    if len(access) != 20 or not access.startswith("ASIA"):
        raise SystemExit("Wrong access key ID format: copy the 20-character AWS_ACCESS_KEY_ID starting with ASIA, not the secret key. Nothing was saved.")
    secret = getpass("AWS secret access key: ").strip()
    if len(secret) != 40:
        raise SystemExit("Wrong secret key format: copy only AWS_SECRET_ACCESS_KEY's 40-character value. Nothing was saved.")
    token = getpass("AWS session token: ").strip()
    region = input("Region shown in your event dashboard: ").strip()
    if not all((access, secret, token, region)):
        raise SystemExit("All three temporary credentials and the event region are required.")
    if any(c.isspace() for c in token) or token.startswith(("export", "AWS_", '"', "'")):
        raise SystemExit("Copy only the session token value, without export, assignment or quotes. Nothing was saved.")
    root = Path.home() / ".aws"
    root.mkdir(mode=0o700, exist_ok=True)
    for name, section, values in [
        ("credentials", profile, {"aws_access_key_id": access, "aws_secret_access_key": secret, "aws_session_token": token}),
        ("config", "default" if profile == "default" else f"profile {profile}", {"region": region, "output": "json"}),
    ]:
        path = root / name
        config = configparser.RawConfigParser()
        config.read(path)
        if not config.has_section(section):
            config.add_section(section)
        for key, value in values.items():
            config.set(section, key, value)
        # Replace only after a full successful write; preserve other profiles.
        temp = path.with_suffix(".workshop.tmp")
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as stream:
            config.write(stream)
        os.chmod(temp, 0o600)
        temp.replace(path)
    print(f"Saved profile {profile} in {region}. Credentials were not printed.")
    print(f"Verify: aws sts get-caller-identity --profile {profile}")


if __name__ == "__main__":
    main()
