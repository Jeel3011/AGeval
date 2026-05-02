"""
ageval/cli.py

Self-serve onboarding CLI for AGeval.
Run with: ageval-setup
"""
import os
import sys

def main():
    print("Welcome to AGeval Onboarding!")
    print("-----------------------------")
    print("This will guide you through setting up AGeval in your project.")
    
    # 1. API Key
    api_key = input("1. Enter your AGeval API Key (or press Enter to skip): ").strip()
    if api_key:
        with open(".env", "a") as f:
            f.write(f"\nAGEVAL_API_KEY={api_key}\n")
        print("✅ Added AGEVAL_API_KEY to .env")
    else:
        print("⚠️ Skipped setting API key.")

    print("\n2. Integration:")
    print("   Which agent framework are you using?")
    print("   1) LangGraph / LangChain")
    print("   2) OpenAI function calling")
    print("   3) Other (CrewAI, AutoGen, custom)")
    choice = input("   Choice (1/2/3): ").strip()

    if choice == "1":
        print("\n👉 To integrate with LangGraph:")
        print("   from ageval import trace_agent")
        print("   result = trace_agent(agent=your_graph, input=messages, agent_id='v1')")
    elif choice == "2":
        print("\n👉 To integrate with OpenAI:")
        print("   from ageval import trace_openai")
        print("   result = trace_openai(client, messages, tools, tool_fns, agent_id='v1', task='...')")
    else:
        print("\n👉 To integrate with any other framework:")
        print("   from ageval import AgentSession")
        print("   with AgentSession(agent_id='v1', task='do X') as session:")
        print("       result = my_tool(args)")
        print("       session.record_step(tool_name='my_tool', tool_output=result, success=True)")

    print("\n🎉 Setup complete! You're ready to evaluate your agents.")
    print("To view your dashboard, open the AGeval UI and connect using your API key.")

if __name__ == "__main__":
    main()
