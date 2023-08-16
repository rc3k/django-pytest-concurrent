from django.conf import settings
import pytest

from pytest_django.plugin import django_db_blocker
from xdist import is_xdist_worker


def _disable_migrations() -> None:
    """
    prevent migrations from running when setting up tests
    """
    from django.conf import settings  # noqa
    from django.core.management.commands import migrate  # noqa

    class DisableMigrations:
        def __contains__(self, item: str) -> bool:
            return True

        def __getitem__(self, item: str) -> None:
            return None

    settings.MIGRATION_MODULES = DisableMigrations()

    class MigrateSilentCommand(migrate.Command):
        def handle(self, *args, **kwargs):
            kwargs["verbosity"] = 0
            return super().handle(*args, **kwargs)

    migrate.Command = MigrateSilentCommand


def pytest_xdist_setupnodes(config, specs):
    """
    this is a hook that's called within xdist before any remote node is set up
    creates a single instance of the test database that can be cloned by node
    """
    from django.test.utils import setup_databases
    _disable_migrations()

    keepdb = config.getvalue('reuse_db')
    createdb = config.getvalue('create_db')
    setup_databases_args = {}
    if keepdb and not createdb:
        setup_databases_args["keepdb"] = True

    with django_db_blocker.__pytest_wrapped__.obj().unblock():
        setup_databases(
            verbosity=config.option.verbose,
            interactive=False,
            **setup_databases_args
        )


@pytest.fixture(scope="session")
def django_db_setup(
    request,
    django_test_environment: None,
    django_db_blocker,
    django_db_use_migrations: bool,
    django_db_keepdb: bool,
    django_db_createdb: bool,
    django_db_modify_db_settings: None,
) -> None:
    """
        Top level fixture to ensure test databases are available
        When running using xdist (parallel tests, multiple CPUs), the test database is cloned into each node
        When running without xdist (single CPU), the test database is setup normally
    """
    from django.test.utils import get_unique_databases_and_mirrors, setup_databases
    from django.db import connections

    setup_databases_args = {}

    if not django_db_use_migrations:
        _disable_migrations()

    if django_db_keepdb and not django_db_createdb:
        setup_databases_args["keepdb"] = True

    with django_db_blocker.unblock():
        if is_xdist_worker(request):
            db_incr = settings.DATABASES['default']["TEST"]["NAME"].split('_')[-1]
            test_databases, mirrored_aliases = get_unique_databases_and_mirrors()
            for db_name, aliases in test_databases.values():
                for alias in aliases:
                    connection = connections[alias]
                    connection.settings_dict["NAME"] = f"test_{settings['default']['name']}"
                    connection.creation.clone_test_db(
                        suffix=db_incr,
                        verbosity=request.config.option.verbose,
                        **setup_databases_args
                    )
                    connection.settings_dict["NAME"] = f"test_{settings['default']['name']}_{db_incr}"
        else:
            setup_databases(
                verbosity=request.config.option.verbose,
                interactive=False,
                **setup_databases_args
            )
