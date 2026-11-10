# openoutreach/config/apps.py
from django.apps import AppConfig


class ConfigAppConfig(AppConfig):
    name = "openoutreach.config"
    # Namespaced like the children's, for the same reason: three app sets share one
    # registry and a bare `config` is exactly the label somebody else will want.
    label = "openoutreach_config"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        # After every app is loaded, so the hub client and the sender can be
        # replaced in place. Importing them while settings is still loading
        # is too early: their models are not registered yet.
        from openoutreach.privacy import install_runtime_guards

        install_runtime_guards()
