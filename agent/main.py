from __future__ import annotations

import asyncio
import logging
from typing import Annotated

import aiohttp
from dotenv import load_dotenv
from livekit.agents import (
    AutoSubscribe,
    JobContext,
    WorkerOptions,
    WorkerType,
    cli,
    llm,
    multimodal,
)
from livekit.plugins import openai

load_dotenv()

logger = logging.getLogger("my-worker")
logger.setLevel(logging.INFO)


async def entrypoint(ctx: JobContext):
    logger.info("starting entrypoint")

    fnc_ctx = llm.FunctionContext()

    @fnc_ctx.ai_callable()
    async def get_weather(
            location: Annotated[
                str, llm.TypeInfo(description="The location to get the weather for")
            ],
    ):
        """Called when the user asks about the weather. This function will return the weather for the given location."""
        logger.info(f"getting weather for {location}")
        url = f"https://wttr.in/{location}?format=%C+%t"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    weather_data = await response.text()
                    # response from the function call is returned to the LLM
                    return f"The weather in {location} is {weather_data}."
                else:
                    raise Exception(
                        f"Failed to get weather data, status code: {response.status}"
                    )

    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    participant = await ctx.wait_for_participant()

    # create a chat context with chat history
    chat_ctx = llm.ChatContext()
    chat_ctx.append(text="请全程用中文和我对话", role="user")

    agent = multimodal.MultimodalAgent(
        model=openai.realtime.RealtimeModel(
            voice="alloy",
            temperature=0.8,
            instructions="You are a helpful assistant",
            turn_detection=openai.realtime.ServerVadOptions(
                threshold=0.6, prefix_padding_ms=200, silence_duration_ms=500
            ),
        ),
        fnc_ctx=fnc_ctx,
        chat_ctx=chat_ctx,
    )
    agent.start(ctx.room, participant)

    @agent.on("agent_speech_committed")
    @agent.on("agent_speech_interrupted")
    def _on_agent_speech_created(msg: llm.ChatMessage):
        # example of truncating the chat context
        max_ctx_len = 10
        chat_ctx = agent.chat_ctx_copy()
        if len(chat_ctx.messages) > max_ctx_len:
            chat_ctx.messages = chat_ctx.messages[-max_ctx_len:]
            # NOTE: The `set_chat_ctx` function will attempt to synchronize changes made
            # to the local chat context with the server instead of completely replacing it,
            # provided that the message IDs are consistent.
            asyncio.create_task(agent.set_chat_ctx(chat_ctx))


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, worker_type=WorkerType.ROOM))
