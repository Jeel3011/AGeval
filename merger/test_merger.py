import os
from dotenv import load_dotenv
load_dotenv()

from supabase import create_client
from merger.merger import run_merger

client = create_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_SERVICE_ROLE_KEY"],
)

result = run_merger(
    client     = client,
    episode_id = "ep_150b4afaaf814679",
    run_id     = "019d3db9-f38f-7511-ae1f-16b9b679f7e4",
    agent_id   = "demo_agent_v1",
    task       = "add two numbers then reverse a string",
)

print(f"merger result: {result}")