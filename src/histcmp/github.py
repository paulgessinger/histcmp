import os

is_github_actions = "GITHUB_ACTIONS" in os.environ


def github_actions_marker(level, message):
    message = message.replace("\n", "%0A")
    return f"::{level} ::{message}"
