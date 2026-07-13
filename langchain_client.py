import asyncio

from dotenv import load_dotenv
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
#from langgraph.prebuilt import create_react_agent
from langchain.agents import create_agent


load_dotenv()

llm = ChatOpenAI()


async def main():
    client = MultiServerMCPClient(
        {
            "math": {
                "command": "python",
                "args": [
                    "/Users/rakeshyadav/TCS-AI-Training/Langchain-MCP/mcp-crash-course/servers/math_server.py"
                ],
                "transport": "stdio", # <-- Added this missing key
            },
            "weather": {
                "url": "http://localhost:8000/sse",
                "transport": "sse",
            },
            "github": {
                "command": "python",
                "args": [
                    "/Users/rakeshyadav/TCS-AI-Training/Langchain-MCP/mcp-crash-course/servers/github_server.py"
                ],
                "transport": "stdio",
            },
        }
    )
    tools = await client.get_tools()
    agent = create_agent(llm, tools)
    # result = await agent.ainvoke({"messages": "What is 2 + 2?"})
    # result = await agent.ainvoke({"messages": "What is the weather in San Francisco?"})
    result = await agent.ainvoke(
        {"messages": "What are the open issues on anthropics/claude-code?"}
    )

    print(result["messages"][-1].content)


if __name__ == "__main__":
    asyncio.run(main())