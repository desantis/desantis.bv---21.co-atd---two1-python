# standard python imports
import base64
import sys

# 3rd party imports
import click

# two1 imports
from two1.lib.server.login import check_setup_twentyone_account
from two1.lib.blockchain.exceptions import DataProviderUnavailableError, DataProviderError
from two1.lib.util.exceptions import TwoOneError, UnloggedException
from two1.lib.util.uxstring import UxString
from two1.lib.wallet import Two1Wallet
from two1.lib.blockchain import TwentyOneProvider
from two1.lib.util.decorators import json_output, check_notifications
from two1.lib.server.analytics import capture_usage
from two1.lib.server import rest_client
from two1.commands.config import TWO1_HOST, TWO1_PROVIDER_HOST, Config
from two1.lib.wallet.two1_wallet import Wallet
from two1.lib.server.machine_auth_wallet import MachineAuthWallet
from two1.lib.server.login import get_password


@click.command()
@click.option('-a', '--accounts', is_flag=True, default=False,
              help='Shows a list of your 21 accounts')
@click.option('-su', '--switchuser', default=None, help='Switch the active user')
@click.option('-sp', '--setpassword', is_flag=True, default=False,
              help='Set/update your 21 password')
@click.option('-u', '--username', default=None, help='The username to login with')
@click.option('-p', '--password', default=None, help='The password to login with')
@json_output
def login(config, accounts, switchuser, setpassword, username, password):
    """Log in to your different 21 accounts."""
    if setpassword:
        return _set_password(config, switchuser)
    elif switchuser or accounts:
        return _switch_user(config, switchuser)
    else:
        username = username or get_username_interactive()
        password = password or get_password_interactive()
        login_with_username_password(config, username, password)


@check_notifications
@capture_usage
def login_with_username_password(config, username, password):
    print("-----")
    print(username)
    print(password)


def get_username_interactive():
    username = click.prompt(UxString.login_username, type=str)
    return username


def get_password_interactive():
    password = click.prompt(UxString.login_password, hide_input=True, type=str)
    return password


@capture_usage
def _set_password(config, user):
    try:
        if not hasattr(config, "username"):
            click.secho(UxString.no_account_found)
            return

        password = get_password(config.username)
        machine_auth = get_machine_auth(config)
        client = rest_client.TwentyOneRestClient(TWO1_HOST,
                                                 machine_auth,
                                                 config.username)
        client.update_password(password)

    except click.exceptions.Abort:
        pass


def get_machine_auth(config):
    if hasattr(config, "machine_auth"):
        machine_auth = config.machine_auth
    else:
        dp = TwentyOneProvider(TWO1_PROVIDER_HOST)
        wallet_path = Two1Wallet.DEFAULT_WALLET_PATH
        if not Two1Wallet.check_wallet_file(wallet_path):
            create_wallet_and_account()
            return

        wallet = Wallet(wallet_path=wallet_path,
                        data_provider=dp)
        machine_auth = MachineAuthWallet(wallet)

    return machine_auth


@capture_usage
def _login(config, user):
    """ Logs into a two1 user account

        Using the rest api and wallet machine auth, _login
        will log into your account and set your authentication credientails
        for all further api calls.

    Args:
        config (Config): config object used for getting .two1 information
        user (str): username
    """
    if config.username:
        click.secho("Currently logged in as: {}".format(config.username), fg="blue")

    # get machine auth
    if hasattr(config, "machine_auth"):
        machine_auth = config.machine_auth
    else:
        dp = TwentyOneProvider(TWO1_PROVIDER_HOST)
        wallet_path = Two1Wallet.DEFAULT_WALLET_PATH
        if not Two1Wallet.check_wallet_file(wallet_path):
            create_wallet_and_account()
            return

        wallet = Wallet(wallet_path=wallet_path,
                        data_provider=dp)
        machine_auth = MachineAuthWallet(wallet)

    client = rest_client.TwentyOneRestClient(TWO1_HOST,
                                             machine_auth)

    # get a list of all usernames for device_id/wallet_pk pair
    res = client.account_info()
    usernames = res.json()["usernames"]
    if len(usernames) == 0:
        create_wallet_and_account()
        return

    else:
        if user is None:
            # interactively select the username
            counter = 1
            click.secho(UxString.registered_usernames_title)

            for user in usernames:
                click.secho("{}- {}".format(counter, user))
                counter += 1

            username_index = -1
            while username_index <= 0 or username_index > len(usernames):
                username_index = click.prompt(UxString.login_prompt, type=int)
                if username_index <= 0 or username_index > len(usernames):
                    click.secho(UxString.login_prompt_invalid_user.format(1, len(usernames)))

            username = usernames[username_index - 1]
        else:
            # log in with provided username
            if user in usernames:
                username = user
            else:
                click.secho(UxString.login_prompt_user_does_not_exist.format(user))
                return

        # save the selection in the config file
        save_config(config, machine_auth, username)


def save_config(config, machine_auth, username):
    """
    Todo:
        Merge this function into _login
    """
    machine_auth_pubkey_b64 = base64.b64encode(
        machine_auth.public_key.compressed_bytes
    ).decode()

    click.secho("Logging in {}".format(username), fg="yellow")
    config.load()
    config.update_key("username", username)
    config.update_key("mining_auth_pubkey", machine_auth_pubkey_b64)
    config.save()


def create_wallet_and_account():
    """ Creates a wallet and two1 account

    Raises:
        TwoOneError: if the data provider is unavailable or an error occurs
    """
    try:
        cfg = Config()
        check_setup_twentyone_account(cfg)
    except DataProviderUnavailableError:
        raise TwoOneError(UxString.Error.connection_cli)
    except DataProviderError:
        raise TwoOneError(UxString.Error.server_err)
    except UnloggedException:
        sys.exit(1)
