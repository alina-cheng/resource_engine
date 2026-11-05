#!/usr/bin/env bash
# Create the demo accounts shown on the login page in the deployed Cognito user pool, with permanent passwords.
# Safe to run again: existing accounts keep their groups and have their passwords reset to the demo values.
#
# Usage:
#   export AWS_PROFILE=<profile>
#   make demo-accounts
#
# The provider account needs its organization in the deployed database, so import the sample data first.
# Without it, the admin and seeker accounts are still created and the script exits with an error.
#
# Optional environment variables:
#   AWS_REGION   default us-west-2
#   APP_URL      default http://<load balancer DNS name>
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="$ROOT/infra/terraform"
REGION="${AWS_REGION:-us-west-2}"
export AWS_REGION="$REGION"

ADMIN_EMAIL="admin@demo.org";       ADMIN_PASSWORD="demo-admin-1"
PROVIDER_EMAIL="provider1@demo.org"; PROVIDER_PASSWORD="demo-provider-1"
SEEKER_EMAIL="ana@demo.org";        SEEKER_PASSWORD="demo-seeker-1"
PROVIDER_ORG="Bay Area Diaper Bank"

fail() { echo "ERROR: $*" >&2; exit 1; }

for tool in terraform aws curl python3; do
  command -v "$tool" >/dev/null || fail "$tool is not installed."
done
aws sts get-caller-identity >/dev/null || fail "AWS credentials are missing or expired. Set AWS_PROFILE and refresh them."

POOL="$(terraform -chdir="$TF_DIR" output -raw cognito_user_pool_id)"
APP_URL="${APP_URL:-http://$(terraform -chdir="$TF_DIR" output -raw alb_dns_name)}"
API="${APP_URL%/}/api"

UPPERCASE="$(aws cognito-idp describe-user-pool --user-pool-id "$POOL" \
  --query 'UserPool.Policies.PasswordPolicy.RequireUppercase' --output text)"
[ "$UPPERCASE" = "False" ] || [ "$UPPERCASE" = "false" ] \
  || fail "The user pool still requires uppercase letters, so it rejects the demo passwords. Apply infra/terraform/data.tf first."

user_exists() {
  aws cognito-idp admin-get-user --user-pool-id "$POOL" --username "$1" >/dev/null 2>&1
}

set_password() {
  aws cognito-idp admin-set-user-password --user-pool-id "$POOL" --username "$1" --password "$2" --permanent
}

# MessageAction=SUPPRESS: these addresses are not ours, so Cognito must not send them invitations.
create_account() {
  local email="$1" name="$2" group="$3" password="$4"
  if ! user_exists "$email"; then
    aws cognito-idp admin-create-user --user-pool-id "$POOL" --username "$email" --message-action SUPPRESS \
      --user-attributes "Name=email,Value=$email" Name=email_verified,Value=true "Name=name,Value=$name" >/dev/null
  fi
  aws cognito-idp admin-add-user-to-group --user-pool-id "$POOL" --username "$email" --group-name "$group"
  set_password "$email" "$password"
  echo "Ready: $email ($group)"
}

json_get() { python3 -c 'import json,sys; print(json.load(sys.stdin)[sys.argv[1]])' "$1"; }

create_account "$ADMIN_EMAIL" "Demo Admin" admin "$ADMIN_PASSWORD"
create_account "$SEEKER_EMAIL" "Ana Diaz" seeker "$SEEKER_PASSWORD"

# The provider goes through the app API because the link to its organization lives in the app database.
LOGIN_BODY="$(EMAIL="$ADMIN_EMAIL" PASSWORD="$ADMIN_PASSWORD" python3 -c \
  'import json,os; print(json.dumps({"email": os.environ["EMAIL"], "password": os.environ["PASSWORD"]}))')"
TOKEN="$(curl --fail --silent --show-error -H 'Content-Type: application/json' -d "$LOGIN_BODY" "$API/auth/login" | json_get token)" \
  || fail "Could not log in to $API as $ADMIN_EMAIL."

ORG_ID="$(curl --fail --silent --show-error --get -H "Authorization: Bearer $TOKEN" \
  --data-urlencode "q=$PROVIDER_ORG" "$API/admin/providers" \
  | ORG="$PROVIDER_ORG" python3 -c '
import json, os, sys
matches = [o["id"] for o in json.load(sys.stdin)["organizations"] if o["name"] == os.environ["ORG"]]
print(matches[0] if matches else "")')"
[ -n "$ORG_ID" ] || fail "\"$PROVIDER_ORG\" is not in the deployed database. Import the sample data, then run this again to create $PROVIDER_EMAIL."

if ! user_exists "$PROVIDER_EMAIL"; then
  BODY="$(EMAIL="$PROVIDER_EMAIL" PASSWORD="$PROVIDER_PASSWORD" ORG_ID="$ORG_ID" python3 -c '
import json, os
print(json.dumps({"role": "provider", "name": "Bay Area Diaper Bank staff", "email": os.environ["EMAIL"],
                  "password": os.environ["PASSWORD"], "org_id": os.environ["ORG_ID"]}))')"
  curl --fail --silent --show-error -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
    -d "$BODY" "$API/admin/users" >/dev/null || fail "Could not create $PROVIDER_EMAIL through the app."
fi
set_password "$PROVIDER_EMAIL" "$PROVIDER_PASSWORD"

LINKED="$(curl --fail --silent --show-error -H "Authorization: Bearer $TOKEN" "$API/admin/providers/$ORG_ID" \
  | EMAIL="$PROVIDER_EMAIL" python3 -c '
import json, os, sys
print(any(u["email"] == os.environ["EMAIL"] for u in json.load(sys.stdin)["users"]))')"
[ "$LINKED" = "True" ] || fail "$PROVIDER_EMAIL exists in Cognito but is not linked to \"$PROVIDER_ORG\"."
echo "Ready: $PROVIDER_EMAIL (provider, $PROVIDER_ORG)"

printf '\nDemo accounts are ready at %s\n' "$APP_URL"
