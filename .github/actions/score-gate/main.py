import os
import sys
import json
import urllib.request

def main():
    api_key = os.environ.get("AGEVAL_API_KEY")
    api_url = os.environ.get("AGEVAL_API_URL", "https://ageval-api.onrender.com").rstrip("/")
    agent_id = os.environ.get("AGEVAL_AGENT_ID")
    min_score = float(os.environ.get("AGEVAL_MIN_SCORE", "0.8"))

    if not api_key:
        print("::error::AGEVAL_API_KEY is required.")
        sys.exit(1)
    if not agent_id:
        print("::error::AGEVAL_AGENT_ID is required.")
        sys.exit(1)

    print(f"Checking latest episodes for agent: {agent_id}")

    try:
        req = urllib.request.Request(
            f"{api_url}/episodes?agent_id={agent_id}&limit=5",
            headers={"Authorization": f"Bearer {api_key}"}
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
            episodes = data.get("episodes", [])
    except Exception as e:
        print(f"::error::Failed to fetch episodes: {e}")
        sys.exit(1)

    if not episodes:
        print(f"::warning::No episodes found for agent {agent_id}. Passing by default.")
        sys.exit(0)

    latest_ep = episodes[0]
    ep_id = latest_ep["episode_id"]

    try:
        req = urllib.request.Request(
            f"{api_url}/episodes/{ep_id}",
            headers={"Authorization": f"Bearer {api_key}"}
        )
        with urllib.request.urlopen(req) as resp:
            ep_data = json.loads(resp.read())
            scores = ep_data.get("scores", [])
    except Exception as e:
        print(f"::error::Failed to fetch scores for episode {ep_id}: {e}")
        sys.exit(1)

    if not scores:
        print(f"::warning::Episode {ep_id} has not been scored yet. Passing by default.")
        sys.exit(0)

    # Assuming the first score (usually rules-based) or the llm_judge score. Let's take average or first.
    # Typically, we care about the 'rules' score or we just take the max.
    score_val = float(scores[0]["score"])

    print(f"Latest episode {ep_id} score: {score_val}")

    if score_val < min_score:
        print(f"::error::Score {score_val} is below the required minimum of {min_score}")
        sys.exit(1)

    print("::notice::AGeval Score Gate passed!")

if __name__ == "__main__":
    main()
