import asyncio

from openai.types.shared import Reasoning

from agents import Agent, ModelSettings, Runner

# If you have a certain reason to use Chat Completions, you can configure the model this way,
# and then you can pass the chat_completions_model to the Agent constructor.
# from openai import AsyncOpenAI
# client = AsyncOpenAI()
# from agents import OpenAIChatCompletionsModel
# chat_completions_model = OpenAIChatCompletionsModel(model="gpt-5", openai_client=client)


async def main():
    agent = Agent(
        name="Knowledgable GPT-5 Assistant",
        instructions="You're a knowledgable assistant. You always provide an interesting answer.",
        model="gpt-5",
        model_settings=ModelSettings(
            reasoning=Reasoning(effort="minimal"),  # "minimal", "low", "medium", "high"
            verbosity="low",  # "low", "medium", "high"
        ),
    )
    user_input = input("Enter something: ")
    result = await Runner.run(agent, user_input)
    print(result.final_output)


if __name__ == "__main__":
    asyncio.run(main())
