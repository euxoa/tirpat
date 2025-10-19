#!/usr/bin/env python3
import asyncio
import json
import httpx

from openai import AzureOpenAI, AsyncAzureOpenAI
from agents import set_default_openai_client, set_default_openai_api, set_tracing_disabled
from agents import Agent, Runner, OpenAIChatCompletionsModel
from agents.mcp import MCPServerStreamableHttp, MCPServerSse
from textwrap import dedent as dd


set_default_openai_api("chat_completions")
set_tracing_disabled(disabled=True)
# This needs to be async, even the sync runner runs async under the hood.
client_4o = AsyncAzureOpenAI(
            api_key="9b39258581ab4d18ae53804c3309806b",
            api_version="2024-12-01-preview",
            azure_endpoint="https://chatgpt-poc-dev.openai.azure.com/",
            azure_deployment="gpt-4o-latest-eu")

set_default_openai_client(client_4o)

async def main():
    # Use async context manager to properly connect to MCP server
    async with MCPServerSse(params={'url': "http://127.0.0.1:8065/sse"}) as mcp_server:
        a = Agent("General agent",
                  instructions="", 
                  tools=[], 
                  mcp_servers=[mcp_server],
                  model=OpenAIChatCompletionsModel(openai_client=client_4o, model=""))
        
        res = await Runner.run(a, "how's weather in tornio now and this week?")
        print(res.final_output)

# Run the async function
asyncio.run(main())
