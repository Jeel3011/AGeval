import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)

# numpy / scikit-learn are only needed for the background clustering job.
# Import them lazily and degrade gracefully so a worker without these optional
# ML dependencies installed can still merge and score episodes — it just skips
# clustering instead of crashing the whole process at import time.
try:
    import numpy as np
    from sklearn.cluster import KMeans
    _CLUSTERING_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only when deps are absent
    np = None  # type: ignore[assignment]
    KMeans = None  # type: ignore[assignment]
    _CLUSTERING_AVAILABLE = False


def run_clustering(client):
    """
    Periodic job: runs K-means on agent tasks and updates episode_clusters.
    We do this per user_id, per agent_id.
    """
    if not _CLUSTERING_AVAILABLE:
        log.warning(
            "Clustering skipped: numpy/scikit-learn not installed. "
            "Install them (pip install numpy scikit-learn) to enable task clustering."
        )
        return

    log.info("Running background clustering job...")
    try:
        # Get all distinct user/agent pairs that have episodes
        resp = client.table("episodes").select("user_id, agent_id").execute()
        if not resp.data:
            return

        pairs = set((row.get("user_id"), row.get("agent_id")) for row in resp.data)

        for user_id, agent_id in pairs:
            if user_id and agent_id:
                _cluster_for_agent(client, user_id, agent_id)

    except Exception as e:
        log.error(f"Clustering job failed: {e}", exc_info=True)

def _cluster_for_agent(client, user_id: str, agent_id: str):
    # Fetch embeddings, tasks, created_at, and outcomes for this agent
    # We join episode_embeddings and episode_scores
    resp = (
        client.table("episodes")
        .select("episode_id, task, created_at, outcome, cluster_id, episode_embeddings(embedding), episode_scores(score)")
        .eq("user_id", user_id)
        .eq("agent_id", agent_id)
        .execute()
    )

    if not resp.data:
        return

    episodes_data = []
    for row in resp.data:
        emb_obj = row.get("episode_embeddings")
        if not emb_obj:
            continue

        if isinstance(emb_obj, list) and len(emb_obj) > 0:
            emb = emb_obj[0].get("embedding")
        elif isinstance(emb_obj, dict):
            emb = emb_obj.get("embedding")
        else:
            continue

        if not emb:
            continue

        import ast
        if isinstance(emb, str):
            try:
                emb = ast.literal_eval(emb)
            except (ValueError, SyntaxError):
                continue

        score = None
        scores_obj = row.get("episode_scores")
        if isinstance(scores_obj, list) and len(scores_obj) > 0:
            score = scores_obj[0].get("score")
        elif isinstance(scores_obj, dict):
            score = scores_obj.get("score")

        episodes_data.append({
            "episode_id": row["episode_id"],
            "task": row["task"] or "Unknown task",
            "cluster_id": row.get("cluster_id"),
            "embedding": emb,
            "score": score,
            "created_at": row.get("created_at"),
            "outcome": row.get("outcome")
        })

    if len(episodes_data) < 4:
        log.info(f"Not enough episodes to cluster for user={user_id} agent={agent_id}")
        return

    # Prepare data for K-means
    X = np.array([ep["embedding"] for ep in episodes_data])

    # Set number of clusters (max 4 as per requirements)
    n_samples = len(episodes_data)
    n_clusters = min(4, max(2, n_samples // 5))

    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init="auto")
    labels = kmeans.fit_predict(X)
    centroids = kmeans.cluster_centers_

    # We want to maintain stable cluster IDs if possible.
    # Fetch existing clusters for this agent
    existing_clusters_resp = client.table("episode_clusters").select("id, centroid").eq("user_id", user_id).eq("agent_id", agent_id).execute()
    existing_clusters = existing_clusters_resp.data or []

    # Process each new cluster
    used_existing_ids = set()
    for cluster_idx in range(n_clusters):
        cluster_episodes = [ep for i, ep in enumerate(episodes_data) if labels[i] == cluster_idx]
        if not cluster_episodes:
            continue

        centroid = centroids[cluster_idx].tolist()

        # Pick the label from the episode closest to the centroid
        distances = [np.linalg.norm(np.array(ep["embedding"]) - centroids[cluster_idx]) for ep in cluster_episodes]
        best_idx = np.argmin(distances)
        cluster_label = cluster_episodes[best_idx]["task"]
        if len(cluster_label) > 100:
            cluster_label = cluster_label[:97] + "..."

        scores = [ep["score"] for ep in cluster_episodes if ep["score"] is not None]
        avg_score = float(np.mean(scores)) if scores else None

        # Calculate Behavioral Drift (week-over-week)
        now = datetime.now(timezone.utc)
        recent_scores = []
        old_scores = []
        for ep in cluster_episodes:
            if ep["score"] is None or not ep.get("created_at"):
                continue
            created_at = datetime.fromisoformat(ep["created_at"].replace("Z", "+00:00"))
            days_old = (now - created_at).days
            if days_old <= 7:
                recent_scores.append(ep["score"])
            elif days_old <= 14:
                old_scores.append(ep["score"])

        drift = None
        if recent_scores and old_scores:
            drift = float(np.mean(recent_scores)) - float(np.mean(old_scores))

        # Failure Pattern Rollup
        top_failing_tool = None
        failed_ep_ids = [ep["episode_id"] for ep in cluster_episodes if ep.get("outcome") == "failure"]
        if failed_ep_ids:
            try:
                # Fetch failed steps for these episodes
                steps_resp = (
                    client.table("episode_steps")
                    .select("tool_name")
                    .in_("episode_id", failed_ep_ids)
                    .eq("success", False)
                    .execute()
                )
                if steps_resp.data:
                    from collections import Counter
                    tools = [s["tool_name"] for s in steps_resp.data]
                    if tools:
                        top_failing_tool = Counter(tools).most_common(1)[0][0]
            except Exception as e:
                log.warning(f"Could not calculate top_failing_tool: {e}")

        # Try to map to an existing cluster to keep IDs stable
        best_match_id = None
        best_match_dist = float('inf')
        for ec in existing_clusters:
            if ec["id"] in used_existing_ids:
                continue
            ec_cent = ast.literal_eval(ec["centroid"]) if isinstance(ec["centroid"], str) else ec["centroid"]
            dist = float(np.linalg.norm(np.array(centroid) - np.array(ec_cent)))
            if dist < 0.5 and dist < best_match_dist:  # nearest existing cluster within threshold
                best_match_dist = dist
                best_match_id = ec["id"]

        if best_match_id:
            used_existing_ids.add(best_match_id)
            cluster_id = best_match_id
            client.table("episode_clusters").update({
                "label": cluster_label,
                "centroid": centroid,
                "episode_count": len(cluster_episodes),
                "avg_score": avg_score,
                "drift": drift,
                "top_failing_tool": top_failing_tool
            }).eq("id", cluster_id).execute()
        else:
            # Create new
            cluster_data = {
                "user_id": user_id,
                "agent_id": agent_id,
                "label": cluster_label,
                "centroid": centroid,
                "episode_count": len(cluster_episodes),
                "avg_score": avg_score,
                "drift": drift,
                "top_failing_tool": top_failing_tool
            }
            resp = client.table("episode_clusters").insert(cluster_data).execute()
            if resp.data:
                cluster_id = resp.data[0]["id"]
            else:
                continue

        # Update episodes
        ep_ids = [ep["episode_id"] for ep in cluster_episodes]
        # Update in batches of 50 to avoid URL length limits in PostgREST
        for i in range(0, len(ep_ids), 50):
            batch = ep_ids[i:i+50]
            client.table("episodes").update({"cluster_id": cluster_id}).in_("episode_id", batch).execute()

        # Recompute peer-relative score baselines for this cluster (§1.2).
        # Best-effort: a missing table or failure here never aborts clustering.
        try:
            from merger.baselines import compute_baselines
            compute_baselines(client, cluster_id, ep_ids)
        except Exception as e:
            log.warning(f"cluster_baselines computation failed for cluster {cluster_id}: {e}")

        # Mine the golden trajectory for this cluster (§1.3), then score each
        # member's adherence to it now that the golden path exists. Best-effort.
        try:
            from merger.procedural import mine_golden_trajectory
            if mine_golden_trajectory(client, cluster_id, user_id, agent_id, ep_ids):
                from eval.trajectory import score_trajectory_adherence
                for eid in ep_ids:
                    try:
                        score_trajectory_adherence(client, eid)
                    except Exception as te:
                        log.debug(f"trajectory scoring failed for {eid}: {te}")
        except Exception as e:
            log.warning(f"procedural_memory mining failed for cluster {cluster_id}: {e}")

    # Mine numeric tool-input baselines for this agent (once, across all its
    # episodes — these are per-agent, not per-cluster). Feeds the live verdict's
    # baseline-outlier layer (LIVE_EVAL_WEDGE_PLAN §1). Best-effort.
    try:
        from merger.input_baselines import mine_input_baselines
        mine_input_baselines(client, user_id, agent_id)
    except Exception as e:
        log.warning(f"tool_input_baselines mining failed for agent {agent_id}: {e}")

    # Old clusters that were not matched can be ignored or deleted
    # We will leave them for drift detection history, or they could be deleted if episode_count = 0.
