"""Give a computer one task after another from your terminal, and watch it work in the live view.

    uv run python -m examples.chat
    uv run python -m examples.chat --computer desktop
    uv run python -m examples.chat --computer android --view text

The computer stays as each task leaves it, so a task can build on the one before. The model is also
told what you asked earlier and what it answered, though not how it got there.
"""

import argparse

import agent
from computers import Android, Browser, Desktop

COMPUTERS = {"browser": Browser, "desktop": Desktop, "android": Android}

parser = argparse.ArgumentParser()
parser.add_argument("--computer", default="browser", choices=COMPUTERS)
parser.add_argument("--model", default="kimi-k3-1-pro", help="name of a Modal Endpoint")
parser.add_argument("--view", choices=["pixels", "text", "both"], help="default: both, or pixels on the desktop")
args = parser.parse_args()

model = agent.modal_endpoint(args.model)
options = {
    "view": args.view,
    "can_ask": True,  # the model may stop and ask you something
    "on_step": lambda step: print(f"  {step.seconds:4.1f}s  {step.summary()}"),
}

with COMPUTERS[args.computer].create() as computer:
    print("Watch it live:", computer.live_view())
    history = []  # (task, answer) pairs: the model's memory of this conversation
    while task := input("\nTask (press Enter alone to quit): ").strip():
        earlier = "".join(f"Earlier you were asked: {asked}\nYou answered: {answer}\n\n" for asked, answer in history)
        record = agent.run(computer, earlier + task, model, **options)
        while record.question:
            reply = input(f"The agent asks: {record.question}\nYour answer: ")
            agent.resume(computer, record, model, reply=reply, **options)
        print("Answer:", record.answer if record.finished else "(stopped before finishing)")
        history.append((task, record.answer or "(you did not finish)"))
