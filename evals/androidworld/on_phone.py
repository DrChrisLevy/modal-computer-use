"""Runs inside the Sandbox: AndroidWorld's own code prepares one task on the phone and later scores it.

    python /tmp/androidworld.py apps              install and configure AndroidWorld's apps (once, see setup.py)
    python /tmp/androidworld.py list              print every task with its step budget
    python /tmp/androidworld.py task NAME SEED    prepare a task, wait for the agent to finish, score it

`task` is one long-running process, like AndroidWorld's own runner, because the task object remembers
what the phone looked like before the agent touched it. It talks to the eval through three files:

    goal.json    written when the phone is ready: {"goal": "..."}
    answer.txt   written by the eval when the agent has finished: what the agent passed to done
    score.json   written in reply: {"score": 1.0} when the task is solved

Either JSON file holds {"error": "..."} instead if that stage failed.
"""

import json
import os
import random
import subprocess
import sys
import time
import traceback

from android_env.wrappers import a11y_grpc_wrapper
from android_world import registry
from android_world.env import env_launcher

FOLDER = "/tmp/androidworld"
TASKS = registry.TaskRegistry().get_registry("android_world")


def connect(install_apps: bool = False):
    """AndroidWorld's handle on the emulator that is already running."""
    return env_launcher.load_and_setup_env(console_port=5554, emulator_setup=install_apps, adb_path="adb")


def write(name: str, **contents) -> None:
    with open(f"{FOLDER}/{name}.part", "w") as file:
        json.dump(contents, file)
    os.rename(f"{FOLDER}/{name}.part", f"{FOLDER}/{name}")  # so a reader never sees half a file


def run_task(name: str, seed: int) -> None:
    os.makedirs(FOLDER, exist_ok=True)
    stage = "goal.json"
    try:
        env = connect()
        env.reset(go_home=True)
        random.seed(seed)
        task = TASKS[name](TASKS[name].generate_random_params() | {"seed": seed})
        task.initialize_task(env)
        # AndroidWorld reads the screen through an accessibility service of its own. Switch it off while the
        # agent works: `uiautomator`, which `Android.describe` uses, suspends other accessibility services
        # each time it runs, and this one can crash and leave a "keeps stopping" dialog on the screen.
        subprocess.run(["adb", "shell", "settings", "delete", "secure", "enabled_accessibility_services"], check=True)
        write(stage, goal=task.goal)

        stage = "score.json"
        while not os.path.exists(f"{FOLDER}/answer.txt"):
            time.sleep(0.5)
        with open(f"{FOLDER}/answer.txt") as file:
            env.interaction_cache = file.read()  # where AndroidWorld's question tasks look for the answer
        # Reconnect, which switches that service back on, so a check that looks at the screen sees it as it
        # is now. Connecting also turns wifi on and airplane mode off; skip that, or it would undo what
        # some tasks ask for.
        a11y_grpc_wrapper.A11yGrpcWrapper.attempt_enable_networking = lambda self: None
        env.controller.refresh_env()
        write(stage, score=task.is_successful(env))
    except Exception as error:  # the exception first, because the eval's results keep only the start
        write(stage, error=f"{type(error).__name__}: {error}\n{traceback.format_exc()[-2000:]}")


if __name__ == "__main__":
    command, *arguments = sys.argv[1:]
    if command == "apps":
        connect(install_apps=True)
    elif command == "list":
        for name, task in sorted(TASKS.items()):
            random.seed(0)
            print(name, int(10 * task(task.generate_random_params()).complexity))  # AndroidWorld's own budget
    elif command == "task":
        run_task(arguments[0], int(arguments[1]))
    sys.stdout.flush()
    os._exit(0)  # a normal exit closes AndroidWorld's environment, which would shut the emulator down
