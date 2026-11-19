"""Runs inside the Sandbox: let the Browser Use library drive the Chromium that is already open.

Reads TASK, MODEL, BASE_URL, API_KEY, REASONING and MAX_STEPS from the environment and prints
one line of JSON with the number of steps taken and the agent's final answer.
"""

import asyncio
import json
import os

from browser_use import Agent, Browser, ChatOpenAI


async def main() -> None:
    model = os.environ["MODEL"]
    llm = ChatOpenAI(
        model=model,
        base_url=os.environ["BASE_URL"],
        api_key=os.environ["API_KEY"],
        reasoning_effort=os.environ["REASONING"],
        reasoning_models=[model],
        timeout=120,
    )
    # keep_alive leaves the browser open afterwards, so the task's check can inspect the page.
    browser = Browser(cdp_url="http://127.0.0.1:9222", keep_alive=True)
    agent = Agent(task=os.environ["TASK"], browser=browser, llm=llm, use_thinking=False, llm_timeout=120)
    history = await agent.run(max_steps=int(os.environ["MAX_STEPS"]))
    print(json.dumps({"steps": history.number_of_steps(), "answer": history.final_result()}))


asyncio.run(main())
