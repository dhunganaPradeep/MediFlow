"""Superset config: Keycloak OIDC login, realm-role -> Superset-role mapping,
Slack + SMTP alert delivery. Mounted read-only into the container."""

import os

from flask_appbuilder.security.manager import AUTH_OAUTH

SECRET_KEY = os.environ["SUPERSET_SECRET_KEY"]

SQLALCHEMY_DATABASE_URI = (
    "postgresql+psycopg2://{u}:{p}@postgres:5432/superset_meta".format(
        u=os.environ["POSTGRES_USER"], p=os.environ["POSTGRES_PASSWORD"]
    )
)

# ---- Keycloak OIDC ----
AUTH_TYPE = AUTH_OAUTH
AUTH_USER_REGISTRATION = True
AUTH_USER_REGISTRATION_ROLE = "Gamma"
AUTH_ROLES_SYNC_AT_LOGIN = True
AUTH_ROLES_MAPPING = {
    "admin": ["Admin"],
    "analyst": ["Alpha"],
    "viewer": ["Gamma"],
}

OAUTH_PROVIDERS = [
    {
        "name": "keycloak",
        "icon": "fa-key",
        "token_key": "access_token",
        "remote_app": {
            "client_id": "superset",
            "client_secret": os.environ["KEYCLOAK_SUPERSET_CLIENT_SECRET"],
            "api_base_url": "http://keycloak:8080/realms/mediflow/protocol/openid-connect/",
            "server_metadata_url": (
                "http://keycloak:8080/realms/mediflow/.well-known/openid-configuration"
            ),
            "client_kwargs": {"scope": "openid profile email roles"},
        },
    }
]


def _map_roles(userinfo: dict) -> list[str]:
    return userinfo.get("realm_roles", [])


from superset.security import SupersetSecurityManager  # noqa: E402


class KeycloakSecurityManager(SupersetSecurityManager):
    def oauth_user_info(self, provider, response=None):
        me = self.appbuilder.sm.oauth_remotes[provider].get("userinfo").json()
        return {
            "username": me["preferred_username"],
            "email": me.get("email", ""),
            "first_name": me.get("given_name", ""),
            "last_name": me.get("family_name", ""),
            "role_keys": _map_roles(me),
        }


CUSTOM_SECURITY_MANAGER = KeycloakSecurityManager

# ---- Alerts & reports ----
FEATURE_FLAGS = {"ALERT_REPORTS": True}
SLACK_API_TOKEN = None  # using incoming webhook via alert recipients instead
WEBDRIVER_BASEURL = "http://superset:8088/"

SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_STARTTLS = True
SMTP_SSL = False
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_MAIL_FROM = os.environ.get("SMTP_USER", "alerts@mediflow.local")

# Proxy awareness (nginx TLS termination)
ENABLE_PROXY_FIX = True
